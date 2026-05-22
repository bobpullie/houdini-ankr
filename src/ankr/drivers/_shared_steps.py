"""Shared 4-step pipeline dispatched by target_kind (hip|hda).

Subcommand context: `ankr track` (hip), `ankr sync` (hip), `ankr track-hda`,
`ankr sync-hda`. Each subcommand's driver dispatches through these four
steps with a target_kind flag.

P1.6 Wave 4 scope: hip branch is reachable; hda branch is preserved 1:1 from
legacy and will be unlocked when T4 wires `ankr track-hda` in a later wave.
Until T4, `target_kind="hda"` raises `NotImplementedError` at each step's
entry — see `_assert_hda_unwired()` below. T4 removes that helper (single
deletion) to unblock the hda branch.

NOTE (P1.6 wave 4): the `custom_hda` literals in the hda branches are
retained — see `_card.py` module note.
"""
from __future__ import annotations

from pathlib import Path
from math import ceil

from ..hda_cache import lookup_hda_cache, safe_hda_id
from ..manifest import Manifest, load_manifest, save_manifest
from ..markdown_gen import render_segment_md, render_skeleton_md
from ..used_by import rebuild_used_by_for_manifest
from ..cross_refs import extract_cross_segment_refs
from ..hou_runtime import extract_external_refs
from ..dataflow import extract_attrib_lifecycle, render_dataflow_md
from ._helpers import (
    _node_type_histogram, _now, _normalize_hashes_with_flags,
    _walk_landmarks, _build_skeleton_graph, _compose_segment_dict,
    compute_segment_meta,
)
from ._card import prepare_card_step


def _assert_hda_unwired(target_kind: str) -> None:
    """Gate the hda branch until T4 wires `_hda` driver + `ankr track-hda`.

    Removed in one line when T4 lands. See module docstring.
    """
    if target_kind == "hda":
        raise NotImplementedError(
            "target_kind='hda' is deferred to P1.6 T4 (ankr track-hda + _hda "
            "driver). The hda branch in _shared_steps is preserved 1:1 from "
            "legacy but not yet exercised by any wired subcommand."
        )


def _hda_card_bundle_paths(safe: str, card_step: dict) -> list[str]:
    """Build HDA commit bundle path list (shared by step_finalize and sync_hda).

    Always includes the umbrella directory. On card success, also includes
    card.yaml, map.yaml, and the two root-level catalog files.
    """
    paths = [f"custom_hda/{safe}/"]
    if (card_step or {}).get("status") == "success":
        paths.extend([
            f"custom_hda/{safe}/card.yaml",
            f"custom_hda/{safe}/map.yaml",
            "custom_hda/index.yaml",
            "custom_hda/_tag_vocabulary.yaml",
        ])
    return paths


def step_prepare(state: dict, target_kind: str = "hip") -> dict:
    """Step 1: normalize inputs, build dirs, compute segments_index, hda_deps, hda_cache_report."""
    if target_kind not in ("hip", "hda"):
        raise ValueError(f"unknown target_kind: {target_kind}")
    _assert_hda_unwired(target_kind)

    docs_root: Path = state["docs_root"]
    chain: list[dict] = state["chain"]
    enriched: list[dict] = state["enriched"]
    narratives: dict = state["narratives"]
    hda_mtime_lookup: dict | None = state.get("hda_mtime_lookup")

    hashes, flags_by_path = _normalize_hashes_with_flags(state["hashes_with_flags"])
    landmark_records = _walk_landmarks(chain)

    if target_kind == "hip":
        hipname: str = state["hipname"]
        endnode_name: str = state["endnode_name"]
        landmark_inputs: dict = state.get("landmark_inputs") or {}
        cross_segment_refs = extract_cross_segment_refs(
            enriched, landmark_records, landmark_inputs)
        objpath1_by_landmark: dict = state.get("objpath1_by_landmark") or {}
        chain_paths = {n["path"] for n in chain}
        external_refs = extract_external_refs(
            landmark_records, objpath1_by_landmark, chain_paths)
        out_dir = docs_root / hipname / endnode_name
    else:  # hda
        hda_type: str = state["hda_type"]
        cross_segment_refs = []
        external_refs = []
        out_dir = docs_root / "custom_hda" / safe_hda_id(hda_type)

    segments_dir = out_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    segments_index = []
    for seg in enriched:
        sid = seg["seg_id"]
        warnings: list[str] = []
        seed_count = sum(len(n.get("random_seeds", []) or []) for n in seg["nodes"])
        if seed_count > 0:
            warnings.append(f"random seed x{seed_count}")
        if any((n.get("flags") or {}).get("bypass") for n in seg["nodes"]):
            warnings.append("bypass")
        narr_text = (narratives.get(sid) or {}).get("narrative", "")
        segments_index.append({"id": sid, "narrative": narr_text, "warnings": warnings})

    hda_deps = sorted({n["hda_type"] for seg in enriched for n in seg["nodes"]
                       if n.get("is_hda") and n.get("hda_type")})

    hda_cache_report: dict = {}
    if hda_mtime_lookup:
        for h in hda_deps:
            mtime = hda_mtime_lookup.get(h, 0.0)
            status, _ = lookup_hda_cache(docs_root, h, mtime)
            hda_cache_report[h] = {"status": status, "mtime": mtime}
    else:
        for h in hda_deps:
            hda_cache_report[h] = {"status": "unknown", "mtime": 0.0}

    now = _now()

    return {
        "hashes": hashes,
        "flags_by_path": flags_by_path,
        "landmark_records": landmark_records,
        "out_dir": out_dir,
        "segments_dir": segments_dir,
        "segments_index": segments_index,
        "hda_deps": hda_deps,
        "hda_cache_report": hda_cache_report,
        "cross_segment_refs": cross_segment_refs,
        "external_refs": external_refs,
        "now": now,
    }


def step_render(state: dict, target_kind: str = "hip") -> dict:
    """Step 2: render segment .md files, skeleton.md, dataflow.md, build narrative_review."""
    if target_kind not in ("hip", "hda"):
        raise ValueError(f"unknown target_kind: {target_kind}")
    _assert_hda_unwired(target_kind)
    enriched: list[dict] = state["enriched"]
    narratives: dict = state["narratives"]
    chain: list[dict] = state["chain"]
    endnode_path: str = state["endnode_path"]
    endnode_name: str = state["endnode_name"]
    hip_meta: dict = state.get("hip_meta", {})
    segments_dir: Path = state["segments_dir"]
    out_dir: Path = state["out_dir"]
    landmark_records: list[dict] = state["landmark_records"]
    segments_index: list[dict] = state["segments_index"]
    hda_deps: list[str] = state["hda_deps"]
    now: str = state["now"]
    cross_segment_refs: list[dict] = state.get("cross_segment_refs", [])
    external_refs: list[dict] = state.get("external_refs", [])

    seg_files: list[str] = []
    all_random_seeds: list = []
    flag_anomalies: list = []
    narrative_review: dict = {}

    for seg in enriched:
        sid = seg["seg_id"]
        for n in seg["nodes"]:
            for s in n.get("random_seeds", []) or []:
                all_random_seeds.append({
                    "segment": sid, "node": s.get("node"),
                    "source": s.get("source"), "value": s.get("value"),
                })
            for fk, fv in (n.get("flags") or {}).items():
                flag_anomalies.append({
                    "segment": sid, "node": n["name"],
                    "flag": f"{fk}={fv}", "note": "추후 확인 필요",
                })

        seg_dict = _compose_segment_dict(seg, narratives, endnode_path)
        md = render_segment_md(seg_dict)
        fname = f"{sid}.md"
        (segments_dir / fname).write_text(md, encoding="utf-8")
        seg_files.append(fname)

        narrative_review[sid] = (narratives.get(sid) or {}).get("narrative", "")

    segment_summary = []
    for seg in enriched:
        meta = compute_segment_meta(seg)
        seg_file = segments_dir / f"{seg['seg_id']}.md"
        file_kb = seg_file.stat().st_size / 1024 if seg_file.exists() else 0.0
        meta["file_kb"] = round(file_kb, 1)
        meta["seg_id"] = seg["seg_id"]
        split_by_file = ceil(file_kb / 15) if file_kb >= 15 else 1
        meta["split"] = max(meta["split"], split_by_file) if max(meta["split"], split_by_file) > 1 else 0
        segment_summary.append(meta)

    graph_nodes, graph_edges = _build_skeleton_graph(chain, landmark_records, endnode_name)

    skeleton = {
        "endnode": endnode_path,
        "hipfile_current": hip_meta.get("hipfile_current", ""),
        "last_sync": now,
        "node_count_total": len(chain),
        "landmark_count": len(landmark_records),
        "segment_count": len(enriched),
        "random_seeds_in_use": all_random_seeds,
        "flag_anomalies": flag_anomalies,
        "unresolved_issues": [],
        "hda_dependencies": hda_deps,
        "node_type_histogram": _node_type_histogram(chain),
        "landmarks": landmark_records,
        "segments_index": segments_index,
        "graph_edges": graph_edges,
        "graph_nodes": graph_nodes,
        "cross_segment_refs": cross_segment_refs,
        "external_refs": external_refs,
        "segment_summary": segment_summary,
    }
    skeleton_path = out_dir / "skeleton.md"
    skeleton_path.write_text(render_skeleton_md(skeleton), encoding="utf-8")

    lifecycle = extract_attrib_lifecycle(enriched)
    dataflow_md = render_dataflow_md(lifecycle, endnode=endnode_path)
    dataflow_path = out_dir / "dataflow.md"
    dataflow_path.write_text(dataflow_md, encoding="utf-8")

    return {
        "seg_files": seg_files,
        "skeleton_path": skeleton_path,
        "narrative_review": narrative_review,
        "dataflow_path": dataflow_path,
        "segment_summary": segment_summary,
    }


def step_manifest(state: dict, target_kind: str = "hip") -> dict:
    """Step 3: load/create manifest, upsert nodes, save, rebuild used_by, prepare card."""
    if target_kind not in ("hip", "hda"):
        raise ValueError(f"unknown target_kind: {target_kind}")
    _assert_hda_unwired(target_kind)

    docs_root: Path = state["docs_root"]
    endnode_name: str = state["endnode_name"]
    endnode_path: str = state["endnode_path"]
    hip_meta: dict = state["hip_meta"]
    chain: list[dict] = state["chain"]
    enriched: list[dict] = state["enriched"]
    narratives: dict = state["narratives"]
    hashes: dict = state["hashes"]
    flags_by_path: dict = state["flags_by_path"]
    landmark_records: list[dict] = state["landmark_records"]
    hda_deps: list[str] = state["hda_deps"]
    now: str = state["now"]
    segment_summary: list[dict] = state.get("segment_summary", [])

    if target_kind == "hip":
        hipname: str = state["hipname"]
        manifest_path = docs_root / hipname / "manifest.yaml"
        ref_prefix = f"{endnode_name}/"
    else:  # hda
        hda_type: str = state["hda_type"]
        walker_result: dict = state["walker_result"]
        manifest_path = docs_root / "custom_hda" / safe_hda_id(hda_type) / "manifest.yaml"
        ref_prefix = "internal/"

    m = load_manifest(manifest_path)
    if m is None:
        manifest_mode = "create"
        if target_kind == "hip":
            m = Manifest(
                hipfile_name=hipname,
                hipfile_current=hip_meta.get("hipfile_current", ""),
                hipfile_path=hip_meta.get("hipfile_path", ""),
                last_sync=now,
                houdini_version=hip_meta.get("houdini_version", ""),
            )
        else:
            m = Manifest(
                hipfile_name=hda_type,
                hipfile_current=hip_meta.get("hipfile_current", ""),
                hipfile_path=hip_meta.get("hipfile_path", ""),
                last_sync=now,
                houdini_version=hip_meta.get("houdini_version", ""),
                kind="hda",
                hda_type=hda_type,
                hda_modification_time=float(walker_result.get("modification_time", 0.0)),
                internal_endnode=endnode_name,
                nested_hdas=walker_result.get("nested_hdas", []),
                spare_parameters_schema=walker_result.get("spare_parameters_schema", []),
            )
    else:
        manifest_mode = "upsert"
        m.hipfile_current = hip_meta.get("hipfile_current", m.hipfile_current)
        m.hipfile_path = hip_meta.get("hipfile_path", m.hipfile_path)
        m.houdini_version = hip_meta.get("houdini_version", m.houdini_version)
        m.last_sync = now
        if target_kind == "hda":
            m.kind = "hda"
            m.hda_type = hda_type
            mt_candidate = walker_result.get("modification_time")
            if mt_candidate:
                m.hda_modification_time = float(mt_candidate)
            m.internal_endnode = endnode_name
            m.nested_hdas = walker_result.get("nested_hdas", m.nested_hdas)
            m.spare_parameters_schema = walker_result.get(
                "spare_parameters_schema", m.spare_parameters_schema)

    if target_kind == "hip":
        m.add_endnode(
            name=endnode_name,
            path=endnode_path,
            skeleton=f"{endnode_name}/skeleton.md",
            node_count=len(chain),
            landmark_count=len(landmark_records),
            segment_count=len(enriched),
            last_sync=now,
        )
    else:
        m.internal_segments = [
            {"id": s["seg_id"], "node_count": len(s["nodes"])}
            for s in enriched
        ]

    m.segment_summary = segment_summary

    node_to_seg: dict = {}
    for seg in enriched:
        for n in seg["nodes"]:
            node_to_seg.setdefault(n["path"], []).append(
                f"{ref_prefix}{seg['seg_id']}")
    if target_kind == "hip":
        for lm in landmark_records:
            node_to_seg.setdefault(lm["path"], []).append(
                f"{ref_prefix}landmark_{lm['id']}")

    for n in chain:
        p = n["path"]
        if p in hashes:
            refs = node_to_seg.get(p, [])
            m.upsert_node(p, n["type"], hashes[p], refs, flags=flags_by_path.get(p))

    if target_kind == "hip":
        for hda in hda_deps:
            m.add_hda_dependency(hda)

    save_manifest(m, manifest_path)

    if target_kind == "hip":
        used_by_written = rebuild_used_by_for_manifest(docs_root, m)
    else:
        used_by_written = []

    card_step = prepare_card_step(
        docs_root=docs_root,
        target_kind=target_kind,
        target_id=hipname if target_kind == "hip" else hda_type,
        manifest=m,
        narratives=narratives,
        diff_result=None,
        temp=docs_root.parent / "temp",
        prefix="ft" if target_kind == "hip" else "ft_hda",
    )

    return {
        "manifest_mode": manifest_mode,
        "manifest_path": manifest_path,
        "used_by_written": used_by_written,
        "card_step": card_step,
    }


def step_finalize(state: dict, target_kind: str = "hip") -> dict:
    """Step 4: assemble commit bundle and final result dict."""
    if target_kind not in ("hip", "hda"):
        raise ValueError(f"unknown target_kind: {target_kind}")
    _assert_hda_unwired(target_kind)

    docs_root: Path = state["docs_root"]
    endnode_name: str = state["endnode_name"]
    manifest_mode: str = state["manifest_mode"]
    used_by_written: list = state["used_by_written"]

    if target_kind == "hip":
        hipname: str = state["hipname"]
        bundle_paths: list[str] = [f"{hipname}/"]
        for p in used_by_written:
            p_path = Path(p) if isinstance(p, str) else p
            bundle_paths.append(str(p_path.relative_to(docs_root)).replace("\\", "/"))
        message = (f"first track: {hipname} {endnode_name}"
                   if manifest_mode == "create"
                   else f"update: {hipname} {endnode_name}")
    else:  # hda
        hda_type: str = state["hda_type"]
        safe = safe_hda_id(hda_type)
        bundle_paths = _hda_card_bundle_paths(safe, state.get("card_step", {}))
        message = (f"first track HDA: {hda_type}"
                   if manifest_mode == "create"
                   else f"update HDA: {hda_type}")

    bundle = {"message": message, "paths": bundle_paths}

    result = {
        "manifest_mode": manifest_mode,
        "out_dir": state["out_dir"],
        "segment_files": state["seg_files"],
        "skeleton_path": state["skeleton_path"],
        "manifest_path": state["manifest_path"],
        "used_by_written": used_by_written,
        "commit_bundle": bundle,
        "hda_cache_report": state.get("hda_cache_report", {}),
        "card_step": state["card_step"],
        "dataflow_path": state.get("dataflow_path"),
    }

    return {"commit_bundle": bundle, "result": result}
