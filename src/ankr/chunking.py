"""Chunking — branch landmark identification + segment splitting.

Splits a linear cook chain into segments using two rules:
1. Multi-input branching / block-boundary nodes act as hard segment breaks
   and become "landmarks" represented separately in the L1 skeleton.
2. Linear runs between landmarks are further split when they exceed
   N=20 nodes or contain more than 3 wrangles.

Pure-Python — no Houdini runtime dependency. Used by `ankr track` / `ankr sync`
and the deadflow tooling.
"""
from __future__ import annotations

# Multi-input branching nodes (data flow merges/forks)
_BRANCH_TYPES = {
    "merge",
    "switch",
    "switch_if",
    "copytopoints",
    "copy_to_points",
    "object_merge",
    "objectmerge",
}

# Block / loop boundary nodes
_BLOCK_BOUNDARY_TYPES = {
    "block_begin",
    "block_end",
    "block_begin_compile",
    "block_end_compile",
}


def is_branch_type(node_type: str) -> bool:
    """Multi-input data branching node?"""
    return node_type.lower() in _BRANCH_TYPES


def is_block_boundary_type(node_type: str) -> bool:
    """foreach / block boundary node?"""
    return node_type.lower() in _BLOCK_BOUNDARY_TYPES


def is_landmark_type(node_type: str) -> bool:
    """Should this node appear as a landmark in L1 skeleton?"""
    return is_branch_type(node_type) or is_block_boundary_type(node_type)


MAX_NODES_PER_SEGMENT = 20
MAX_WRANGLES_PER_SEGMENT = 3


def _is_wrangle(node: dict) -> bool:
    return "wrangle" in node["type"].lower()


def _split_linear_run(linear_nodes: list[dict]) -> list[list[dict]]:
    """Split a linear (no branches) node sequence by N=20 + wrangle 3 rule."""
    if not linear_nodes:
        return []

    segments: list[list[dict]] = []
    current: list[dict] = []
    current_wrangles = 0

    for node in linear_nodes:
        is_w = _is_wrangle(node)
        would_exceed_count = len(current) >= MAX_NODES_PER_SEGMENT
        would_exceed_wrangles = is_w and current_wrangles >= MAX_WRANGLES_PER_SEGMENT

        if (would_exceed_count or would_exceed_wrangles) and current:
            segments.append(current)
            current = []
            current_wrangles = 0

        current.append(node)
        if is_w:
            current_wrangles += 1

    if current:
        segments.append(current)
    return segments


def split_segments(nodes: list[dict]) -> list[list[dict]]:
    """Split a node sequence into segments.

    Branch landmarks act as hard boundaries — they are excluded from the resulting
    segments and represented separately by the caller (skeleton).

    Linear runs between branches are further split by N=20 / wrangle 3 rule.
    """
    segments: list[list[dict]] = []
    linear: list[dict] = []

    for node in nodes:
        if is_landmark_type(node["type"]):
            if linear:
                segments.extend(_split_linear_run(linear))
                linear = []
        else:
            linear.append(node)

    if linear:
        segments.extend(_split_linear_run(linear))

    return segments


def walk_landmarks(chain: list[dict]) -> list[dict]:
    """Build landmark records (M1/M2 branches, B1/B2 blocks) from a linear
    chain. Each record has id, path, type, kind, between (label).

    This lives in chunking (not drivers) so it can be imported inside
    Houdini without pulling in yaml-dependent modules.
    """
    # Step 1: parse chain into walk events with before/after run indices
    walk_parsed: list = []
    for i, n in enumerate(chain):
        if is_landmark_type(n["type"]):
            runs_before = 0
            in_run = False
            for k in range(i):
                if not is_landmark_type(chain[k]["type"]):
                    if not in_run:
                        in_run = True
                        runs_before += 1
                else:
                    in_run = False
            has_next_run = any(not is_landmark_type(c["type"]) for c in chain[i + 1:])
            before = f"seg_{runs_before:02d}" if runs_before > 0 else "(src)"
            after = f"seg_{runs_before + 1:02d}" if has_next_run else "(out)"
            walk_parsed.append(("L", n, before, after))
        else:
            walk_parsed.append(("N", n, None, None))

    # Step 2: assign IDs (M for branches, B for blocks)
    landmark_records: list = []
    m_ctr = 0
    b_ctr = 0
    for kind, n, before, after in walk_parsed:
        if kind != "L":
            continue
        if is_branch_type(n["type"]):
            m_ctr += 1
            lid = f"M{m_ctr}"
            kind_label = "branch"
        else:
            b_ctr += 1
            lid = f"B{b_ctr}"
            kind_label = "block"
        landmark_records.append({
            "id": lid,
            "path": n["path"],
            "type": n["type"],
            "kind": kind_label,
            "between": f"{before} → {after}",
        })
    return landmark_records
