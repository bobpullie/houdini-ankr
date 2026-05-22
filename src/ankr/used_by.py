"""Inverse index: node/HDA type → reference sites across manifests.

Consumes `Manifest` objects (manifest.yaml) and emits per-type `used_by.md`
files under the HDA docs subdirectory. Aggregates across ALL hip manifests
in `docs_root` so cross-hip refs are preserved.

Pure-Python — no Houdini runtime dependency. Used by `ankr track` /
`ankr sync` after manifest updates.

NOTE (P1.6 wave 4): the `custom_hda` literal in this module is held over from
the legacy layout where docs_root/custom_hda/ was the HDA subtree. The canonical
config exposes this as `docs.hda_subdir` and the driver layer will inject the
resolved path so this module loses the literal. Until drivers are ported, the
literal still matches the config default and behavior is unchanged.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .manifest import Manifest, load_manifest


def _split_reference(ref: str) -> tuple[str, str]:
    """`OUT_Curves/seg_03_bevel` → (`OUT_Curves`, `seg_03_bevel`).

    References without a `/` are treated as endnode-level landmarks.
    """
    if "/" in ref:
        endnode, segment = ref.split("/", 1)
        return endnode, segment
    return ref, ""


def build_inverse_index(manifests: Iterable[Manifest]) -> dict[str, list[dict]]:
    """Build `{type_id: [reference, ...]}` across all manifests.

    Each reference dict:
        hipname, endnode, segment, node_path, bypass
    """
    index: dict[str, list[dict]] = defaultdict(list)
    for m in manifests:
        for node_path, info in m.nodes.items():
            type_id = info.get("type", "")
            if not type_id:
                continue
            flags = info.get("flags", {}) or {}
            bypass = bool(flags.get("bypass", False))
            for ref in info.get("referenced_by", []) or []:
                endnode, segment = _split_reference(ref)
                index[type_id].append({
                    "hipname": m.hipfile_name,
                    "endnode": endnode,
                    "segment": segment,
                    "node_path": node_path,
                    "bypass": bypass,
                })
    return dict(index)


def render_used_by_md(target_id: str, references: list[dict]) -> str:
    """Render used_by.md for a single target. Groups by hipname."""
    lines: list[str] = [f"# used_by — `{target_id}`", ""]

    if not references:
        lines.append("사용처 없음.")
        lines.append("")
        return "\n".join(lines)

    by_hip: dict[str, list[dict]] = defaultdict(list)
    for r in references:
        by_hip[r["hipname"]].append(r)

    total = len(references)
    lines.append(f"총 참조: **{total}** (hip {len(by_hip)}개)")
    lines.append("")

    for hipname in sorted(by_hip.keys()):
        lines.append(f"## {hipname}")
        lines.append("")
        lines.append("| endnode | segment | node | flags |")
        lines.append("|---|---|---|---|")
        for r in by_hip[hipname]:
            flag_cell = "⚠️ bypass" if r.get("bypass") else ""
            lines.append(
                f"| {r['endnode']} | {r['segment']} | `{r['node_path']}` | {flag_cell} |"
            )
        lines.append("")

    return "\n".join(lines)


def _safe_type_id(type_id: str) -> str:
    """Filesystem-safe HDA type id: `bluei::X::1.0` → `bluei__X__1.0`."""
    return type_id.replace("::", "__")


def rebuild_used_by_for_manifest(
    docs_root: Path,
    current_manifest: Manifest,
    all_manifests: Iterable[Manifest] | None = None,
) -> list[Path]:
    """Re-render `<docs_root>/custom_hda/<safe_id>/used_by.md` for every HDA type
    declared in `current_manifest.hda_dependencies`.

    Inverse index aggregates references across ALL manifests under `docs_root`
    (auto-discovered via `<docs_root>/*/manifest.yaml`) so cross-hip refs are
    preserved. Pass `all_manifests` explicitly to override discovery (tests).

    Returns list of Paths actually written.
    """
    docs_root = Path(docs_root)

    if all_manifests is None:
        loaded: list[Manifest] = []
        for mf in sorted(docs_root.glob("*/manifest.yaml")):
            m = load_manifest(mf)
            if m is None:
                continue
            # Plan 2 Task C §4 (b): HDA manifests do NOT participate in
            # the global used_by index. Defensive filter even though the
            # depth-1 glob already excludes custom_hda/<safe>/manifest.yaml.
            if m.kind != "hip":
                continue
            loaded.append(m)
        # Replace the on-disk copy of current_manifest with the in-memory one
        # so unsaved updates from the caller are reflected.
        replaced = False
        for i, m in enumerate(loaded):
            if m.hipfile_name == current_manifest.hipfile_name:
                loaded[i] = current_manifest
                replaced = True
                break
        if not replaced:
            loaded.append(current_manifest)
        manifests = loaded
    else:
        manifests = list(all_manifests)

    index = build_inverse_index(manifests)

    written: list[Path] = []
    hdas_dir = docs_root / "custom_hda"
    for type_id in current_manifest.hda_dependencies:
        refs = index.get(type_id, [])
        md = render_used_by_md(target_id=type_id, references=refs)
        target = hdas_dir / _safe_type_id(type_id) / "used_by.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        written.append(target)
    return written
