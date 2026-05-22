"""Hip-level driver functions: first_track, sync_endnode, rerender_edited_segments.

Subcommand context: `ankr track` (first_track) and `ankr sync` (sync_endnode).
Pure Python — Houdini lazy-imports live in `hou_runtime`. The driver layer
itself never touches `hou`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..manifest import load_manifest, save_manifest
from ..markdown_gen import render_segment_md
from ..used_by import rebuild_used_by_for_manifest
from ..hou_runtime import extract_external_refs
from ._helpers import _now, _normalize_hashes_with_flags, _compose_segment_dict, _walk_landmarks
from ._shared_steps import step_prepare, step_render, step_manifest, step_finalize
from ._card import prepare_card_step


def first_track(
    *,
    endnode_path: str,
    endnode_name: str,
    hipname: str,
    hip_meta: dict,
    chain: list[dict],
    enriched: list[dict],
    narratives: dict,
    hashes_with_flags: dict,
    docs_root: Path,
    hda_mtime_lookup: dict | None = None,
    landmark_inputs: dict | None = None,
    objpath1_by_landmark: dict | None = None,
) -> dict:
    """Track an endnode for the first time (or add it to an existing manifest).

    `hip_meta` shape: `{hipfile_current, hipfile_path, houdini_version}`.
    `hashes_with_flags` shape: `{path: {hash, flags}}` (new) or `{path: hash}`
    (legacy — flags will be empty).

    Returns a dict:
        manifest_mode: "create" | "upsert"
        out_dir: Path
        segment_files: list[str]
        skeleton_path: Path
        manifest_path: Path
        used_by_written: list[Path]
        commit_bundle: {"message": str, "paths": list[str]}
    """
    state: dict = {
        "endnode_path": endnode_path,
        "endnode_name": endnode_name,
        "hipname": hipname,
        "hip_meta": hip_meta,
        "chain": chain,
        "enriched": enriched,
        "narratives": narratives,
        "hashes_with_flags": hashes_with_flags,
        "docs_root": Path(docs_root),
        "hda_mtime_lookup": hda_mtime_lookup,
        "landmark_inputs": landmark_inputs or {},
        "objpath1_by_landmark": objpath1_by_landmark or {},
    }
    for step in (step_prepare, step_render, step_manifest, step_finalize):
        state.update(step(state, target_kind="hip"))
    return state["result"]


def sync_endnode(
    *,
    endnode_name: str,
    hipname: str,
    hashes_with_flags: dict,
    extracted: list[dict],
    narratives: dict,
    docs_root: Path,
    hip_meta: Optional[dict] = None,
    chain: list[dict] | None = None,
    objpath1_by_landmark: dict | None = None,
) -> dict:
    """Re-render only the segments affected by changes for `endnode_name`.

    The diff is **scoped to the target endnode** (via `restrict_to_endnode`),
    so a multi-endnode manifest will not register sibling endnodes' nodes
    as `deleted`.

    `extracted` is the list of fresh node dicts (output of
    `extract_segment_nodes`) for the current chain.

    Returns:
        diff: {changed, added, deleted}
        re_rendered: list of seg_id strings actually re-written
        manifest_path: Path
        used_by_written: list[Path]
        commit_bundle: {message, paths}
    """
    docs_root = Path(docs_root)
    hashes, flags_by_path = _normalize_hashes_with_flags(hashes_with_flags)

    manifest_path = docs_root / hipname / "manifest.yaml"
    m = load_manifest(manifest_path)
    if m is None:
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    diff = m.diff_against_current(
        hashes,
        current_flags=flags_by_path or None,
        restrict_to_endnode=endnode_name,
    )
    affected = m.affected_segments(diff)

    new_by_path = {n["path"]: n for n in extracted}
    re_rendered: list[str] = []

    seg_dir = docs_root / hipname / endnode_name / "segments"

    for seg_ref in sorted(affected):
        parts = seg_ref.split("/", 1)
        if len(parts) != 2 or parts[0] != endnode_name:
            continue
        sid = parts[1]
        if sid.startswith("landmark_"):
            continue

        seg_paths = [
            p for p, info in m.nodes.items()
            if any(ref == f"{endnode_name}/{sid}" for ref in info.get("referenced_by", []))
        ]
        ordered = [new_by_path[p] for p in seg_paths if p in new_by_path]
        if not ordered:
            continue

        narr = narratives.get(sid, {}) or {}
        seeds: list = []
        for n in ordered:
            for s in (n.get("random_seeds") or []):
                seeds.append(s)
        seg_dict = {
            "segment_id": sid,
            "endnode": "",
            "upstream_landmark": "",
            "downstream_landmark": "",
            "node_count": len(ordered),
            "data": narr.get("data", {}),
            "random_seeds": seeds,
            "narrative": narr.get("narrative", ""),
            "issues": [],
            "nodes": ordered,
        }
        md = render_segment_md(seg_dict)
        target = seg_dir / f"{sid}.md"
        target.write_text(md, encoding="utf-8")
        re_rendered.append(sid)

    for path in diff["changed"]:
        existing = m.nodes[path]
        m.upsert_node(
            path,
            existing["type"],
            hashes[path],
            existing["referenced_by"],
            flags=flags_by_path.get(path) if flags_by_path else None,
        )

    m.previous_sync = m.last_sync
    m.last_sync = _now()
    if hip_meta:
        m.hipfile_current = hip_meta.get("hipfile_current", m.hipfile_current)
        m.hipfile_path = hip_meta.get("hipfile_path", m.hipfile_path)
        m.houdini_version = hip_meta.get("houdini_version", m.houdini_version)

    save_manifest(m, manifest_path)

    used_by_written = rebuild_used_by_for_manifest(docs_root, m)

    external_refs: list[dict] = []
    if chain and objpath1_by_landmark:
        landmark_records = _walk_landmarks(chain)
        chain_paths = {n["path"] for n in chain}
        external_refs = extract_external_refs(
            landmark_records, objpath1_by_landmark, chain_paths,
        )
        skeleton_path = docs_root / hipname / endnode_name / "skeleton.md"
        if skeleton_path.exists():
            _patch_skeleton_external_refs(skeleton_path, external_refs)

    total_changes = len(diff["changed"]) + len(diff["added"]) + len(diff["deleted"])
    if total_changes > 0:
        card_step = prepare_card_step(
            docs_root=docs_root,
            target_kind="hip",
            target_id=hipname,
            manifest=m,
            narratives=narratives,
            diff_result=diff,
            temp=docs_root.parent / "temp",
            prefix="sync",
        )
    else:
        card_step = {"status": "skipped", "reason": "no_changes"}

    bundle_paths: list[str] = [f"{hipname}/"]
    for p in used_by_written:
        p_path = Path(p) if isinstance(p, str) else p
        bundle_paths.append(str(p_path.relative_to(docs_root)).replace("\\", "/"))
    bundle = {
        "message": f"sync: {hipname} ({len(re_rendered)} segments changed)",
        "paths": bundle_paths,
    }

    return {
        "diff": diff,
        "re_rendered": re_rendered,
        "manifest_path": manifest_path,
        "used_by_written": used_by_written,
        "commit_bundle": bundle,
        "card_step": card_step,
        "external_refs": external_refs,
    }


def rerender_edited_segments(state: dict, edited_sids: list[str]) -> None:
    """Re-render segment .md files after narrative edits (graph layer HITL).

    For each sid in edited_sids, reads the updated narrative text from
    ``state["narrative_review"][sid]``, patches the narratives dict, rebuilds
    the segment dict via ``_compose_segment_dict``, re-renders to markdown, and
    overwrites the segment file on disk.

    This function is intentionally side-effect-only (no return value).
    It is NOT called by the first_track() pipeline — it exists for the
    LangGraph HITL layer to call after human review of narrative_review.
    """
    enriched: list[dict] = state["enriched"]
    narratives: dict = state["narratives"]
    endnode_path: str = state["endnode_path"]
    segments_dir: Path = state["segments_dir"]
    narrative_review: dict = state.get("narrative_review", {})

    enriched_by_sid = {seg["seg_id"]: seg for seg in enriched}

    for sid in edited_sids:
        seg = enriched_by_sid.get(sid)
        if seg is None:
            continue
        patched_narratives = dict(narratives)
        existing = dict(patched_narratives.get(sid) or {})
        existing["narrative"] = narrative_review.get(sid, existing.get("narrative", ""))
        patched_narratives[sid] = existing

        seg_dict = _compose_segment_dict(seg, patched_narratives, endnode_path)
        md = render_segment_md(seg_dict)
        (segments_dir / f"{sid}.md").write_text(md, encoding="utf-8")


def _patch_skeleton_external_refs(skeleton_path: Path, external_refs: list[dict]) -> None:
    """Replace the '## 외부 참조' section in an existing skeleton.md."""
    text = skeleton_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## 외부 참조":
            start_idx = i
        elif start_idx is not None and line.startswith("## "):
            end_idx = i
            break

    new_section: list[str] = []
    if external_refs:
        new_section.append("## 외부 참조")
        new_section.append("")
        new_section.append("| 랜드마크 | object_merge 경로 | 소스 경로 | 위치 |")
        new_section.append("|----------|-------------------|-----------|------|")
        for eref in external_refs:
            new_section.append(
                f"| {eref['landmark_id']} | {eref['landmark_path']} "
                f"| {eref['source_path']} | {eref.get('between', '')} |"
            )
        new_section.append("")

    if start_idx is not None:
        if end_idx is None:
            end_idx = len(lines)
        lines[start_idx:end_idx] = new_section
    elif external_refs:
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if line.strip() == "## 세그먼트 인덱스":
                insert_at = i
                break
        lines[insert_at:insert_at] = new_section

    skeleton_path.write_text("\n".join(lines), encoding="utf-8")
