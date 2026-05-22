"""L0/L1 card system — build, validate, render.

Card pipeline: build CardInput from manifest + narratives + vocabulary,
compute input_hash for change detection, generate Haiku prompt, validate
the returned CardOutput, and write card.yaml (HDA) + map.yaml.

Haiku invocation is handled externally by the agent via Agent tool. This
module provides data preparation (_build_haiku_prompt, serialize_card_input)
and finalization (finalize_card) only.

Pure-Python — no Houdini runtime dependency.

NOTE (P1.6 wave 4): the `custom_hda` literals in `_card_dir` and
`update_global_index` are held over from the legacy layout. The canonical
config exposes this as `docs.hda_subdir` and the driver layer will inject the
resolved path so this module loses the literal. Until drivers are ported, the
literal still matches the config default and behavior is unchanged.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from .manifest import Manifest
from .tag_vocabulary import (
    TagVocabulary, validate_tags,
    serialize_vocab_for_haiku,
)


@dataclass
class CardInput:
    kind: Literal["hip", "hda"]
    id: str
    segments: list[dict]
    parms: list[dict]
    nested_hdas: list[str]
    node_histogram: dict[str, int]
    node_hashes: dict[str, str]
    anomalies: list[dict]
    recent_changes: dict | None
    vocab_version: int
    input_hash: str = ""


@dataclass
class CardOutput:
    purpose: str
    pipeline: list[dict]
    parms_roles: dict[str, str]
    tags: list[str]
    proposed_tags: list[dict]
    nested_purposes: dict[str, str]


def _node_type_histogram(nodes: dict[str, dict]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for info in nodes.values():
        t = info.get("type", "")
        if t:
            hist[t] = hist.get(t, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def _extract_anomalies(nodes: dict[str, dict]) -> list[dict]:
    anomalies: list[dict] = []
    for path, info in nodes.items():
        flags = info.get("flags", {})
        for flag_name in ("bypass", "template", "lock"):
            if flags.get(flag_name):
                anomalies.append({"path": path, "flag": flag_name, "note": ""})
    return anomalies


def build_card_input(
    manifest: Manifest,
    narratives: dict,
    vocab: TagVocabulary,
    recent_changes: dict | None = None,
) -> CardInput:
    """Assemble CardInput from a manifest + narratives + vocabulary."""
    if manifest.kind == "hda":
        segments_source = manifest.internal_segments
        seg_list = []
        for seg in segments_source:
            sid = seg["id"]
            narr = narratives.get(sid, {})
            narr_line = narr.get("narrative", "").split("\n")[0] if narr.get("narrative") else ""
            key_nodes = [
                p.rsplit("/", 1)[-1] for p, info in manifest.nodes.items()
                if any(r.endswith(f"/{sid}") for r in info.get("referenced_by", []))
            ][:3]
            seg_list.append({
                "slug": sid,
                "narrative_first_line": narr_line,
                "key_nodes": key_nodes,
            })
        parms = [
            {"name": p["name"], "label": p.get("label", ""), "type": p.get("type", ""),
             "default": p.get("default", ""), "folder": p.get("folder", "")}
            for p in manifest.spare_parameters_schema
        ]
        target_id = manifest.hda_type
    else:
        seg_ids: list[str] = []
        for endnode in manifest.endnodes:
            en_name = endnode["name"]
            for p, info in manifest.nodes.items():
                for ref in info.get("referenced_by", []):
                    if ref.startswith(f"{en_name}/seg_"):
                        seg_id = ref.split("/", 1)[1]
                        if seg_id not in seg_ids:
                            seg_ids.append(seg_id)
        seg_list = []
        for sid in seg_ids:
            narr = narratives.get(sid, {})
            narr_line = narr.get("narrative", "").split("\n")[0] if narr.get("narrative") else ""
            seg_list.append({
                "slug": sid,
                "narrative_first_line": narr_line,
                "key_nodes": [],
            })
        parms = []
        target_id = manifest.hipfile_name

    node_hashes = {p: info.get("hash", "") for p, info in manifest.nodes.items()}

    return CardInput(
        kind=manifest.kind,
        id=target_id,
        segments=seg_list,
        parms=parms,
        nested_hdas=list(manifest.nested_hdas) if manifest.kind == "hda"
                     else list(manifest.hda_dependencies),
        node_histogram=_node_type_histogram(manifest.nodes),
        node_hashes=node_hashes,
        anomalies=_extract_anomalies(manifest.nodes),
        recent_changes=recent_changes,
        vocab_version=vocab.version,
    )


def compute_input_hash(card_input: CardInput) -> str:
    """SHA1 of canonical JSON of input fields. Used as the input_hash gate."""
    payload = {
        "chain_node_hashes": card_input.node_hashes,
        "parm_signature": [(p["name"], p["type"], str(p["default"])) for p in card_input.parms],
        "nested_list": sorted(card_input.nested_hdas),
        "segment_count": len(card_input.segments),
        "pipeline_input": [s["slug"] + s["narrative_first_line"] for s in card_input.segments],
        "vocab_version": card_input.vocab_version,
        "anomalies": [(a["path"], a["flag"]) for a in card_input.anomalies],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _card_dir(docs_root: Path, card_id: str, kind: str) -> Path:
    """Resolve card directory path based on kind."""
    if kind == "hda":
        safe = card_id.replace("::", "__")
        return docs_root / "custom_hda" / safe
    else:
        return docs_root / card_id


def should_skip_haiku(
    docs_root: Path,
    card_id: str,
    new_input_hash: str,
    *,
    kind: str = "hda",
) -> bool:
    """Return True if input_hash matches stored AND card files exist.

    input_hash gate: skip Haiku rendering if:
    1. stored .card_input_hash matches new_input_hash
    2. card.yaml and map.yaml exist
    """
    target = _card_dir(docs_root, card_id, kind)
    hash_file = target / ".card_input_hash"
    if not hash_file.exists():
        return False
    stored = hash_file.read_text(encoding="utf-8").strip()
    if stored != new_input_hash:
        return False
    if kind == "hda":
        return (target / "card.yaml").exists() and (target / "map.yaml").exists()
    else:
        return (target / "map.yaml").exists()


def validate_card_output(
    out: CardOutput,
    *,
    segment_count: int,
    vocab: TagVocabulary,
) -> dict:
    """Validate Haiku CardOutput. Returns {ok, errors, accepted_tags, rejected_tags}.

    Checks:
    1. purpose is non-empty
    2. pipeline length matches segment_count
    3. tags are partitioned into accepted/rejected via vocabulary
    """
    errors: list[str] = []

    if not out.purpose:
        errors.append("Missing purpose")

    if len(out.pipeline) != segment_count:
        errors.append(
            f"Segment count mismatch: pipeline has {len(out.pipeline)}, "
            f"expected {segment_count}"
        )

    accepted, rejected = validate_tags(out.tags, vocab)

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "accepted_tags": accepted,
        "rejected_tags": rejected,
    }


def render_card_yaml(out: CardOutput, manifest: Manifest) -> str:
    """Render L0 card.yaml for HDA. Raises ValueError for hip manifests."""
    if manifest.kind != "hda":
        raise ValueError("L0 card.yaml is HDA-only — hip manifests get map.yaml only")

    parms_list = []
    for p in manifest.spare_parameters_schema:
        parms_list.append({
            "name": p["name"],
            "label": p.get("label", ""),
            "type": p.get("type", ""),
            "default": p.get("default", ""),
            "folder": p.get("folder", ""),
            "role": out.parms_roles.get(p["name"], ""),
        })

    io_section = {
        "inputs": [{"idx": 0, "kind": "SOP", "role": ""}],
        "outputs": [{"idx": 0, "kind": "SOP", "role": ""}],
        "creates_attrs": [],
        "consumes_attrs": [],
    }

    card = {
        "type": manifest.hda_type,
        "version": manifest.hda_type.rsplit("::", 1)[-1] if "::" in manifest.hda_type else "",
        "last_sync": manifest.last_sync,
        "purpose": out.purpose,
        "io": io_section,
        "parms": parms_list,
        "tags": out.tags,
    }
    return yaml.safe_dump(card, sort_keys=False, allow_unicode=True)


def render_map_yaml(
    out: CardOutput,
    manifest: Manifest,
    *,
    recent_changes: dict | None = None,
) -> str:
    """Render L1 map.yaml for hip or HDA."""
    if manifest.kind == "hda":
        scale = {
            "node_count": len(manifest.nodes),
            "segment_count": len(manifest.internal_segments),
        }
        target_id = manifest.hda_type
    else:
        total_nodes = len(manifest.nodes)
        total_segs = sum(e.get("segment_count", 0) for e in manifest.endnodes)
        chain_length = sum(e.get("node_count", 0) for e in manifest.endnodes)
        scale = {
            "node_count": total_nodes,
            "segment_count": total_segs,
            "chain_length": chain_length,
        }
        target_id = manifest.hipfile_name

    pipeline = []
    for p in out.pipeline:
        entry: dict = {"stage": p["stage"], "segment": p["segment"]}
        if p.get("key_nodes"):
            entry["key_nodes"] = p["key_nodes"]
        pipeline.append(entry)

    nested_list = []
    for hda_type in (manifest.nested_hdas if manifest.kind == "hda"
                     else manifest.hda_dependencies):
        safe = hda_type.replace("::", "__")
        entry = {
            "type": hda_type,
            "card": f"../{safe}/card.yaml",
            "purpose": out.nested_purposes.get(hda_type, ""),
        }
        nested_list.append(entry)

    map_data: dict = {
        "kind": manifest.kind,
        "id": target_id,
        "last_sync": manifest.last_sync,
        "scale": scale,
        "pipeline": pipeline,
        "node_histogram": _node_type_histogram(manifest.nodes),
        "nested_hdas": nested_list,
        "anomalies": _extract_anomalies(manifest.nodes),
    }

    if recent_changes is not None:
        for cs in recent_changes.get("changed_segments", []):
            seg_num = cs.get("segment", "")
            hint = ""
            for p in pipeline:
                if str(p["segment"]) == str(seg_num):
                    hint = p["stage"]
                    break
            cs["hint"] = hint
        map_data["recent_changes"] = {
            "last_sync": manifest.last_sync,
            "previous_sync": getattr(manifest, "previous_sync", None) or "",
            "summary": recent_changes.get("summary", ""),
            "changed_segments": recent_changes.get("changed_segments", []),
            "added_nodes": recent_changes.get("added_nodes", []),
            "deleted_nodes": recent_changes.get("deleted_nodes", []),
        }

    map_data["anchors"] = {
        "skeleton": "./skeleton.md",
        "segments_dir": "./segments/",
        "manifest": "./manifest.yaml",
    }

    return yaml.safe_dump(map_data, sort_keys=False, allow_unicode=True)


def write_card_artifacts(
    *,
    target_dir: Path,
    kind: str,
    card_yaml_str: str | None,
    map_yaml_str: str,
    input_hash: str,
) -> None:
    """Write card.yaml (HDA only), map.yaml, and .card_input_hash to target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    if kind == "hda" and card_yaml_str is not None:
        (target_dir / "card.yaml").write_text(card_yaml_str, encoding="utf-8")
    (target_dir / "map.yaml").write_text(map_yaml_str, encoding="utf-8")
    (target_dir / ".card_input_hash").write_text(input_hash, encoding="utf-8")


def update_global_index(
    docs_root: Path,
    hda_id: str,
    card_summary: dict,
) -> None:
    """Update custom_hda/index.yaml with card summary for one HDA.
    card_summary shape: {type, purpose, tags, last_sync}."""
    from datetime import datetime
    index_path = docs_root / "custom_hda" / "index.yaml"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    hdas = data.get("hdas", [])
    hdas = [h for h in hdas if h.get("type") != hda_id]
    safe = hda_id.replace("::", "__")
    hdas.append({
        "type": hda_id,
        "purpose": card_summary.get("purpose", ""),
        "tags": card_summary.get("tags", []),
        "card": f"{safe}/card.yaml",
        "last_sync": card_summary.get("last_sync", ""),
    })

    data["generated_at"] = datetime.now().isoformat(timespec="minutes")
    data["hdas"] = hdas

    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _build_haiku_prompt(input_data: dict, vocab_data: dict) -> str:
    """Build the Haiku prompt for card generation."""
    kind = input_data["kind"]
    kind_label = "HDA" if kind == "hda" else "hip 네트워크"
    segments_json = json.dumps(input_data["segments"], indent=2, ensure_ascii=False)
    parms_json = json.dumps(input_data.get("parms", []), indent=2, ensure_ascii=False)
    nested_json = json.dumps(input_data.get("nested_hdas", []), ensure_ascii=False)
    histogram_json = json.dumps(input_data.get("node_histogram", {}), indent=2, ensure_ascii=False)
    anomalies_json = json.dumps(input_data.get("anomalies", []), indent=2, ensure_ascii=False)
    vocab_json = json.dumps(vocab_data, indent=2, ensure_ascii=False)

    return f"""You are a Houdini Technical Artist. Generate a structured card for a {kind_label}.

## Target
id: {input_data["id"]}
kind: {kind}

## Segments
{segments_json}

## Parameters
{parms_json}

## Nested HDAs
{nested_json}

## Node Type Histogram
{histogram_json}

## Anomalies (bypass/template/lock)
{anomalies_json}

## Tag Vocabulary (use ONLY these canonical tag names)
{vocab_json}

---

Return a JSON object with this exact structure:
{{
  "purpose": "이 {kind_label}가 무엇을 하는지 한 줄 한국어 설명",
  "pipeline": [
    {{"stage": "이 단계가 하는 일 (한국어, 간결)", "segment": "segment slug", "key_nodes": ["node1"]}}
  ],
  "parms_roles": {{"param_name": "이 파라미터의 역할 (한국어)"}},
  "tags": ["vocabulary에서 선택한 canonical 태그 3~7개"],
  "proposed_tags": [{{"tag": "어휘집에 없지만 필요한 태그", "suggested_category": "추천 카테고리"}}],
  "nested_purposes": {{"hda_type": "한 줄 설명 (한국어)"}}
}}

Rules:
1. pipeline: 각 segment마다 정확히 하나의 entry. segment 순서 유지.
2. tags: 반드시 vocabulary의 canonical 태그만 사용. 적합한 태그 없으면 proposed_tags에 추가.
3. parms_roles: 파라미터가 없으면 빈 dict {{}}.
4. nested_purposes: nested HDA가 없으면 빈 dict {{}}.
5. proposed_tags: 필요 없으면 빈 리스트 [].

IMPORTANT: Return ONLY the JSON object. No markdown fencing, no explanation, no comments."""


def _extract_json_from_response(raw_text: str) -> dict:
    """Extract JSON dict from Haiku response, handling optional markdown fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


def serialize_card_input(card_input: CardInput, vocab: TagVocabulary) -> dict:
    """Serialize CardInput + vocab into a JSON-writable dict for Haiku prompt."""
    return {
        "kind": card_input.kind,
        "id": card_input.id,
        "segments": card_input.segments,
        "parms": card_input.parms,
        "nested_hdas": card_input.nested_hdas,
        "node_histogram": card_input.node_histogram,
        "anomalies": card_input.anomalies,
        "vocab": serialize_vocab_for_haiku(vocab),
    }


def build_haiku_prompt_from_file(card_input_path: Path) -> str:
    """Load card_input.json and return the Haiku prompt string."""
    data = json.loads(card_input_path.read_text(encoding="utf-8"))
    vocab_data = data.pop("vocab", {})
    return _build_haiku_prompt(data, vocab_data)


def finalize_card(
    *,
    card_output_json: dict,
    card_input: CardInput,
    manifest: Manifest,
    vocab: TagVocabulary,
    target_dir: Path,
    temp: Path,
) -> dict:
    """Validate Haiku output and write card.yaml / map.yaml.

    Returns {status: "success"|"failed", ...}.
    Called by the agent after receiving Haiku subagent response.
    """
    out = CardOutput(
        purpose=card_output_json.get("purpose", ""),
        pipeline=card_output_json.get("pipeline", []),
        parms_roles=card_output_json.get("parms_roles", {}),
        tags=card_output_json.get("tags", []),
        proposed_tags=card_output_json.get("proposed_tags", []),
        nested_purposes=card_output_json.get("nested_purposes", {}),
    )

    validation = validate_card_output(
        out,
        segment_count=len(card_input.segments),
        vocab=vocab,
    )

    if not validation["ok"]:
        return {"status": "failed", "errors": validation["errors"]}

    accepted_tags = validation["accepted_tags"]
    rejected_tags = validation["rejected_tags"]

    out.tags = accepted_tags
    if rejected_tags:
        for rt in rejected_tags:
            out.proposed_tags.append({"tag": rt, "suggested_category": ""})

    card_yaml = render_card_yaml(out, manifest) if manifest.kind == "hda" else None
    map_yaml = render_map_yaml(out, manifest, recent_changes=card_input.recent_changes)

    write_card_artifacts(
        target_dir=target_dir,
        kind=manifest.kind,
        card_yaml_str=card_yaml,
        map_yaml_str=map_yaml,
        input_hash=card_input.input_hash,
    )

    failed_path = target_dir / "card.yaml.failed"
    if failed_path.exists():
        failed_path.unlink()

    temp.mkdir(parents=True, exist_ok=True)
    (temp / "card_output.json").write_text(
        json.dumps(card_output_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "status": "success",
        "accepted_tags": accepted_tags,
        "proposed_tags": out.proposed_tags,
        "purpose": out.purpose,
    }
