"""Markdown generation for skeleton.md (L1) and segment.md (L2).

Pure-Python renderers — emit Mermaid diagrams, YAML frontmatter, and tables
from already-prepared dicts. No file I/O, no Houdini runtime.

Used by `ankr track` (initial render) and `ankr sync` (re-render affected
segments).
"""
from __future__ import annotations
import yaml


def _frontmatter(data: dict) -> str:
    """Render dict as yaml frontmatter."""
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def _render_node_wrangle(node: dict, idx: int) -> str:
    lines = [
        f"### {idx}. {node['name']} ({node['type']})",
    ]
    if "runover" in node:
        lines.append(f"- **runover**: {node['runover']}")
    if node.get("reads"):
        lines.append(f"- **reads**: {', '.join(node['reads'])}")
    if node.get("writes"):
        lines.append(f"- **writes**: {', '.join(node['writes'])}")
    if node.get("params_non_default"):
        lines.append("- **params (디폴트와 다른 것만)**:")
        for k, v in node["params_non_default"].items():
            lines.append(f"  - {k}: {v}")
    if node.get("vex_code"):
        lines.append("- **VEX**:")
        lines.append("  ```vex")
        for line in node["vex_code"].splitlines():
            lines.append(f"  {line}")
        lines.append("  ```")
    if node.get("flags"):
        flag_str = ", ".join(f"{k}={v}" for k, v in node["flags"].items())
        lines.append(f"- **flags**: {flag_str}")
    else:
        lines.append("- **flags**: ok")
    return "\n".join(lines)


def _render_node_data_transform(node: dict, idx: int) -> str:
    lines = [
        f"### {idx}. {node['name']} ({node['type']})",
    ]
    if node.get("reads"):
        lines.append(f"- **reads**: {', '.join(node['reads'])}")
    if node.get("writes"):
        lines.append(f"- **writes**: {', '.join(node['writes'])}")
    if node.get("params_non_default"):
        lines.append("- **params (디폴트와 다른 것만)**:")
        for k, v in node["params_non_default"].items():
            marker = ""
            if "seed" in k.lower():
                marker = " ⚠️ random seed"
            lines.append(f"  - {k}: {v}{marker}")
    if node.get("flags"):
        flag_str = ", ".join(f"{k}={v}" for k, v in node["flags"].items())
        lines.append(f"- **flags**: {flag_str}")
    else:
        lines.append("- **flags**: ok")
    if node.get("seed_note"):
        lines.append(f"- {node['seed_note']}")
    return "\n".join(lines)


def _render_node_passthrough(node: dict, idx: int) -> str:
    return f"### {idx}. {node['name']} ({node['type']}) — passthrough"


def _render_node(node: dict, idx: int) -> str:
    kind = node.get("kind", "data_transform")
    if kind == "wrangle":
        return _render_node_wrangle(node, idx)
    elif kind == "passthrough":
        return _render_node_passthrough(node, idx)
    else:
        return _render_node_data_transform(node, idx)


def render_segment_md(seg: dict) -> str:
    """Render a segment dict to markdown body."""
    fm = {
        "segment_id": seg["segment_id"],
        "endnode": seg["endnode"],
        "upstream_landmark": seg.get("upstream_landmark", ""),
        "downstream_landmark": seg.get("downstream_landmark", ""),
        "node_count": seg.get("node_count", len(seg.get("nodes", []))),
        "data": seg.get("data", {}),
        "random_seeds": seg.get("random_seeds", []),
        "narrative": seg.get("narrative", ""),
        "issues": seg.get("issues", []),
    }

    parts = [_frontmatter(fm)]
    parts.append(f"\n# {seg['segment_id']}\n")
    parts.append("## 노드 시퀀스 (cook chain 순서, 상류 → 하류)\n")

    for idx, node in enumerate(seg.get("nodes", []), start=1):
        parts.append(_render_node(node, idx))
        parts.append("")

    if seg.get("issues"):
        parts.append("## 미해결 이슈")
        for iss in seg["issues"]:
            parts.append(f"- {iss}")

    return "\n".join(parts) + "\n"


_MERMAID_SHAPES = {
    "rect": ("[", "]"),
    "diamond": ("{", "}"),
    "subroutine": ("[[", "]]"),
    "circle": ("((", "))"),
    "rounded": ("(", ")"),
    "hex": ("{{", "}}"),
}


def _mermaid_node(node_id: str, label: str, shape: str) -> str:
    open_, close = _MERMAID_SHAPES.get(shape, ("[", "]"))
    return f"{node_id}{open_}{label}{close}"


def render_skeleton_md(sk: dict) -> str:
    """Render skeleton dict to markdown body."""
    fm = {
        "endnode": sk["endnode"],
        "hipfile_current": sk.get("hipfile_current", ""),
        "last_sync": sk.get("last_sync", ""),
        "node_count_total": sk.get("node_count_total", 0),
        "landmark_count": sk.get("landmark_count", 0),
        "segment_count": sk.get("segment_count", 0),
        "random_seeds_in_use": sk.get("random_seeds_in_use", []),
        "flag_anomalies": sk.get("flag_anomalies", []),
        "unresolved_issues": sk.get("unresolved_issues", []),
        "hda_dependencies": sk.get("hda_dependencies", []),
    }
    if sk.get("cross_segment_refs"):
        fm["cross_segment_refs"] = sk["cross_segment_refs"]
    if sk.get("external_refs"):
        fm["external_refs"] = sk["external_refs"]

    endnode_name = sk["endnode"].rsplit("/", 1)[-1]
    parts = [_frontmatter(fm)]
    parts.append(f"\n# 골격: {endnode_name}\n")

    parts.append("## 위상도\n")
    parts.append("```mermaid")
    parts.append("graph TB")
    graph_nodes = sk.get("graph_nodes", {})
    for nid, ninfo in graph_nodes.items():
        parts.append(f"  {_mermaid_node(nid, ninfo['label'], ninfo.get('shape', 'rect'))}")
    for edge in sk.get("graph_edges", []):
        label = edge.get("label", "")
        if label:
            parts.append(f"  {edge['from']} -->|{label}| {edge['to']}")
        else:
            parts.append(f"  {edge['from']} --> {edge['to']}")
    for xref in sk.get("cross_segment_refs", []):
        from_short = "_".join(xref["from_segment"].split("_")[:2])
        to_short = "_".join(xref["to_segment"].split("_")[:2])
        hint = ", ".join(xref.get("data_hint", []))
        if hint:
            parts.append(f'  {from_short} -.->|"{hint}"| {to_short}')
        else:
            parts.append(f"  {from_short} -.-> {to_short}")
    parts.append("```\n")

    if sk.get("landmarks"):
        parts.append("## 랜드마크 표\n")
        parts.append("| ID  | 노드 경로                  | 종류                          | 입/출력             |")
        parts.append("|-----|---------------------------|-------------------------------|---------------------|")
        for lm in sk["landmarks"]:
            kind_label = lm.get("type", lm.get("kind", ""))
            inputs = f" ({lm['inputs']} inputs)" if lm.get("inputs") else ""
            parts.append(
                f"| {lm['id']} | {lm['path']} | {kind_label}{inputs} | {lm.get('between', '')} |"
            )
        parts.append("")

    if sk.get("external_refs"):
        parts.append("## 외부 참조\n")
        parts.append("| 랜드마크 | object_merge 경로 | 소스 경로 | 위치 |")
        parts.append("|----------|-------------------|-----------|------|")
        for eref in sk["external_refs"]:
            parts.append(
                f"| {eref['landmark_id']} | {eref['landmark_path']} "
                f"| {eref['source_path']} | {eref.get('between', '')} |"
            )
        parts.append("")

    # 세그먼트 메타 (before segments_index)
    if sk.get("segment_summary"):
        parts.append("## 세그먼트 메타\n")
        parts.append("| seg_id | nodes | wrangles | vex_lines | file_kb | split |")
        parts.append("|--------|-------|----------|-----------|---------|-------|")
        for sm in sk["segment_summary"]:
            split_str = str(sm["split"]) if sm["split"] else "-"
            parts.append(
                f"| {sm['seg_id']} | {sm['nodes']} | {sm['wrangles']} "
                f"| {sm['vex_lines']} | {sm['file_kb']:.1f} | {split_str} |"
            )
        parts.append("")

    parts.append("## 세그먼트 인덱스")
    for s in sk.get("segments_index", []):
        warning = " ⚠️ " + ", ".join(s["warnings"]) if s.get("warnings") else ""
        parts.append(f"- [{s['id']}](segments/{s['id']}.md) — {s['narrative']}{warning}")
    parts.append("")

    return "\n".join(parts) + "\n"
