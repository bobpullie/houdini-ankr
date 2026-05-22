"""Attribute/group lifecycle extraction for dataflow.md (L1.5 layer).

Scans enriched segment data to track where each attribute and group is
created, consumed, and deleted across the entire cook chain. Renders to
markdown table for the L1.5 dataflow view.

Pure-Python — no Houdini runtime dependency. Used by `ankr track` and the
deadflow detection pipeline.

NOTE (P1.6 wave 4): the `custom_hda` literal in `parse_consumed_from_kb` is
held over from the legacy layout. The canonical config exposes this as
`docs.hda_subdir` and the driver layer will inject the resolved path so this
module loses the literal. Until drivers are ported, the literal still matches
the config default and behavior is unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml


# Markdown table separator cells are made up of `-`, `:`, and whitespace
# (e.g. `---`, `:---`, `:---:`, `---:`). Length 1+ to avoid matching the
# empty leading cell of a `| col |` row.
_SEPARATOR_CELL_RE = re.compile(r"^[\s:-]+$")


def extract_attrib_lifecycle(enriched: list[dict]) -> dict:
    """Extract attribute and group lifecycle from enriched segments.

    Returns dict with keys 'attribs' and 'groups', each mapping
    name -> {created_in: [...], consumed_in: [...], deleted_in: [...]}.
    """
    attribs: dict[str, dict] = {}
    groups: dict[str, dict] = {}

    def _ensure_attrib(name: str) -> dict:
        if name not in attribs:
            attribs[name] = {"created_in": [], "consumed_in": [], "deleted_in": []}
        return attribs[name]

    def _ensure_group(name: str) -> dict:
        if name not in groups:
            groups[name] = {"created_in": [], "consumed_in": [], "deleted_in": []}
        return groups[name]

    for seg in enriched:
        sid = seg["seg_id"]
        for node in seg.get("nodes", []):
            # Attribute writes → created
            for attr in node.get("writes", []):
                info = _ensure_attrib(attr)
                if sid not in info["created_in"]:
                    info["created_in"].append(sid)

            # Attribute reads → consumed
            for attr in node.get("reads", []):
                info = _ensure_attrib(attr)
                if sid not in info["consumed_in"]:
                    info["consumed_in"].append(sid)

            # Group writes → created
            for grp in node.get("groups_write", []):
                info = _ensure_group(grp)
                if sid not in info["created_in"]:
                    info["created_in"].append(sid)

            # Group reads → consumed
            for grp in node.get("groups_read", []):
                info = _ensure_group(grp)
                if sid not in info["consumed_in"]:
                    info["consumed_in"].append(sid)

            # attribdelete → deleted
            if node.get("type") == "attribdelete":
                for pkey in ("ptdel", "primdel", "vtxdel", "dtldel"):
                    val = (node.get("params_non_default") or {}).get(pkey, "")
                    if val:
                        for attr_name in val.split():
                            info = _ensure_attrib(attr_name)
                            if sid not in info["deleted_in"]:
                                info["deleted_in"].append(sid)

            # groupdelete → group deleted
            if node.get("type") == "groupdelete":
                pattern = (node.get("params_non_default") or {}).get("group1", "")
                if pattern:
                    for grp_name in pattern.split():
                        clean = grp_name.lstrip("!").rstrip("*")
                        if clean:
                            info = _ensure_group(clean)
                            if sid not in info["deleted_in"]:
                                info["deleted_in"].append(sid)

    return {"attribs": attribs, "groups": groups}


def render_dataflow_md(lifecycle: dict, endnode: str) -> str:
    """Render dataflow.md from lifecycle data."""
    fm = yaml.safe_dump({"endnode": endnode, "layer": "L1.5"},
                        sort_keys=False, allow_unicode=True)
    parts = [f"---\n{fm}---\n"]
    parts.append(f"# Dataflow: {endnode.rsplit('/', 1)[-1]}\n")

    # Attribute flow table
    parts.append("## 어트리뷰트 흐름\n")
    parts.append("| attrib | created_in | consumed_in | deleted_in | status |")
    parts.append("|--------|-----------|-------------|------------|--------|")
    for name in sorted(lifecycle["attribs"]):
        info = lifecycle["attribs"][name]
        status = "DEAD" if not info["consumed_in"] else "LIVE"
        parts.append(
            f"| {name} "
            f"| {', '.join(info['created_in'])} "
            f"| {', '.join(info['consumed_in'])} "
            f"| {', '.join(info['deleted_in'])} "
            f"| {status} |"
        )
    parts.append("")

    # Dead attribute warnings
    dead = {n: i for n, i in lifecycle["attribs"].items() if not i["consumed_in"]}
    if dead:
        parts.append("## Dead Attribute 경고\n")
        for name, info in sorted(dead.items()):
            created = ", ".join(info["created_in"]) or "불명"
            deleted = ", ".join(info["deleted_in"]) or "삭제 없음"
            parts.append(f"- `{name}`: {created} 생성 → {deleted}")
        parts.append("")

    # Group flow table
    parts.append("## 그룹 흐름\n")
    parts.append("| group | created_in | consumed_in | deleted_in | status |")
    parts.append("|-------|-----------|-------------|------------|--------|")
    for name in sorted(lifecycle["groups"]):
        info = lifecycle["groups"][name]
        status = "DEAD" if not info["consumed_in"] else "LIVE"
        parts.append(
            f"| {name} "
            f"| {', '.join(info['created_in'])} "
            f"| {', '.join(info['consumed_in'])} "
            f"| {', '.join(info['deleted_in'])} "
            f"| {status} |"
        )
    parts.append("")

    return "\n".join(parts) + "\n"


def parse_consumed_from_kb(docs_root, hda_safe_id: str) -> dict | None:
    """Return {'attribs': set[str], 'groups': set[str]} of names with non-empty
    `consumed_in` column in the HDA's dataflow.md. Returns None if KB missing.
    """
    kb = Path(docs_root) / "custom_hda" / hda_safe_id / "dataflow.md"
    if not kb.exists():
        return None
    text = kb.read_text(encoding="utf-8")

    def _extract_table(heading: str) -> list[list[str]]:
        idx = text.find(heading)
        if idx < 0:
            return []
        block = text[idx:]
        rows = []
        for line in block.splitlines()[1:]:  # skip heading
            if line.startswith("## ") and rows:
                break
            if not line.startswith("|"):
                continue
            # Robust markdown table separator detection. A separator row
            # consists of cells made entirely of `-`, `:`, and whitespace.
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and all(_SEPARATOR_CELL_RE.match(c) for c in cells if c):
                continue
            if cells and cells[0] and cells[0].lower() not in ("attrib", "group"):
                rows.append(cells)
        return rows

    attribs: set[str] = set()
    for row in _extract_table("## 어트리뷰트 흐름"):
        if len(row) >= 3 and row[2]:  # consumed_in non-empty
            attribs.add(row[0])

    groups: set[str] = set()
    for row in _extract_table("## 그룹 흐름"):
        if len(row) >= 3 and row[2]:
            groups.add(row[0])

    return {"attribs": attribs, "groups": groups}
