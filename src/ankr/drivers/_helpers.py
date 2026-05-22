"""Helper utilities shared across driver submodules.

Subcommand context: `ankr track` (and future `ankr sync`, `ankr track-hda`,
`ankr sync-hda`). Pure Python — no Houdini dependency.
"""
from __future__ import annotations

from datetime import datetime
from math import ceil

from ..chunking import is_branch_type, is_landmark_type, walk_landmarks
from ..vex_analyzer import count_vex_lines


def _node_type_histogram(chain: list[dict]) -> dict[str, int]:
    """Count node types from a chain. Used in skeleton frontmatter (O6).
    Sorted by descending count then alphabetic for stable output.
    """
    hist: dict[str, int] = {}
    for n in chain:
        t = n.get("type", "")
        if t:
            hist[t] = hist.get(t, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _normalize_hashes_with_flags(raw: dict) -> tuple[dict, dict]:
    """Accept either legacy `{path: hash}` or new `{path: {hash, flags}}`."""
    hashes: dict = {}
    flags_by_path: dict = {}
    for p, v in raw.items():
        if isinstance(v, dict):
            hashes[p] = v["hash"]
            flags_by_path[p] = v.get("flags", {})
        else:
            hashes[p] = v
    return hashes, flags_by_path


def _walk_landmarks(chain: list[dict]) -> list[dict]:
    """Delegate to chunking.walk_landmarks (kept for backward compat)."""
    return walk_landmarks(chain)


def _build_skeleton_graph(chain: list[dict], landmark_records: list[dict],
                          endnode_name: str) -> tuple[dict, list]:
    """Build mermaid graph nodes + edges from a chain, in upstream→endnode order."""
    graph_nodes: dict = {"SRC": {"label": "(src)", "shape": "rect"}}
    graph_edges: list = []

    run_counter = 0
    prev_id = "SRC"
    run_started = False
    for n in chain:
        if not is_landmark_type(n["type"]):
            if not run_started:
                run_counter += 1
                seg_id_short = f"seg_{run_counter:02d}"
                graph_nodes[seg_id_short] = {"label": seg_id_short, "shape": "rect"}
                graph_edges.append({"from": prev_id, "to": seg_id_short})
                prev_id = seg_id_short
                run_started = True
        else:
            run_started = False
            lm = next((l for l in landmark_records if l["path"] == n["path"]), None)
            lid = lm["id"] if lm else n["name"]
            shape = "diamond" if is_branch_type(n["type"]) else "hex"
            graph_nodes[lid] = {"label": f"{n['type']}: {n['name']}", "shape": shape}
            graph_edges.append({"from": prev_id, "to": lid})
            prev_id = lid
    graph_nodes["OUT"] = {"label": endnode_name, "shape": "rect"}
    graph_edges.append({"from": prev_id, "to": "OUT"})
    return graph_nodes, graph_edges


def split_segments_by_landmarks(chain: list[dict]) -> list[list[dict]]:
    """Split a linear chain into segment node-lists, using landmark types
    as boundaries. Identical run-walking pattern used by the hip-side
    first_track function (extracted here for reuse by first_track_hda).
    """
    runs: list[list[dict]] = []
    current: list = []
    for n in chain:
        if is_landmark_type(n["type"]):
            if current:
                runs.append(current)
                current = []
        else:
            current.append(n)
    if current:
        runs.append(current)
    return runs


def _compose_segment_dict(seg: dict, narratives: dict, endnode_path: str) -> dict:
    sid = seg["seg_id"]
    narr = narratives.get(sid, {})
    seeds: list = []
    for n in seg["nodes"]:
        for s in n.get("random_seeds", []) or []:
            seeds.append(s)
    return {
        "segment_id": sid,
        "endnode": endnode_path,
        "upstream_landmark": "",
        "downstream_landmark": "",
        "node_count": len(seg["nodes"]),
        "data": narr.get("data", {}),
        "random_seeds": seeds,
        "narrative": narr.get("narrative", ""),
        "issues": [],
        "nodes": seg["nodes"],
    }


def compute_segment_meta(seg: dict) -> dict:
    """Compute segment metadata for skeleton.md summary table.

    Returns dict with: nodes, wrangles, vex_lines, split.
    (file_kb is computed later after segment.md is written to disk.)
    """
    nodes = seg.get("nodes", [])
    wrangles = 0
    vex_lines = 0
    for n in nodes:
        if n.get("kind") == "wrangle":
            wrangles += 1
            vex_lines += count_vex_lines(n.get("vex_code", ""))

    split_by_vex = ceil(vex_lines / 200) if vex_lines >= 200 else 1
    split = split_by_vex if split_by_vex > 1 else 0

    return {
        "nodes": len(nodes),
        "wrangles": wrangles,
        "vex_lines": vex_lines,
        "split": split,
    }
