"""Cross-segment reference extraction.

Detects DAG connections that cross segment boundaries via landmark nodes
(merges/switches). Each cross-ref ties a source node in one segment to a
landmark in another segment, with the data attributes hinted on the source.

Pure-Python — no Houdini runtime dependency. Used by `ankr track` to embed
cross-refs in skeleton.md frontmatter and to draw dotted Mermaid edges.
"""
from __future__ import annotations


def _resolve_seg_id(short_id: str, full_ids: list[str]) -> str | None:
    """Map short ID like ``"seg_03"`` to full ID like ``"seg_03_scatter"``
    by prefix matching.  Returns *None* if no match found.
    """
    for fid in full_ids:
        if fid == short_id or fid.startswith(short_id + "_"):
            return fid
    return None


def extract_cross_segment_refs(
    enriched: list[dict],
    landmark_records: list[dict],
    landmark_inputs: dict[str, list[str | None]],
) -> list[dict]:
    """Return a list of cross-segment reference dicts.

    Parameters
    ----------
    enriched:
        Segment dicts, each with ``seg_id`` and ``nodes[]``
        (each node has ``path``, ``writes``, etc.).
    landmark_records:
        Landmark dicts with ``id``, ``path``, ``type``, ``kind``,
        ``between`` (format: ``"seg_01 → seg_02"``).
    landmark_inputs:
        Mapping of landmark path → ordered list of input node paths.
        ``None`` entries represent disconnected input slots.

    Returns
    -------
    list[dict]
        Each dict: ``from_segment``, ``from_node``, ``to_segment``,
        ``to_node``, ``to_input_idx``, ``data_hint``.
    """
    # 1. Build node_index: {node_path: (seg_id, writes)}
    node_index: dict[str, tuple[str, list]] = {}
    for seg in enriched:
        for node in seg["nodes"]:
            node_index[node["path"]] = (seg["seg_id"], node.get("writes", []))

    # Collect all full segment IDs for prefix resolution
    all_seg_ids = [seg["seg_id"] for seg in enriched]

    # 2. Build landmark_to_dest: {landmark_path: dest_full_seg_id}
    landmark_to_dest: dict[str, str | None] = {}
    for lm in landmark_records:
        between = lm.get("between", "")
        # Format: "seg_01 → seg_02" or "seg_01 → (out)"
        parts = between.split(" → ")
        if len(parts) == 2:
            dest_short = parts[1].strip()
            if dest_short == "(out)":
                landmark_to_dest[lm["path"]] = None
            else:
                landmark_to_dest[lm["path"]] = _resolve_seg_id(dest_short, all_seg_ids)
        else:
            landmark_to_dest[lm["path"]] = None

    # 3. For each landmark in landmark_inputs, check inputs 1+ for cross-refs
    results: list[dict] = []
    for lm_path, inputs in landmark_inputs.items():
        dest_seg = landmark_to_dest.get(lm_path)
        if dest_seg is None:
            continue

        lm_node_name = lm_path.rsplit("/", 1)[-1]

        for idx, inp in enumerate(inputs):
            # Skip input 0 (main chain) and None entries
            if idx == 0 or inp is None:
                continue

            # Look up source node
            if inp not in node_index:
                continue  # external node, skip

            src_seg, src_writes = node_index[inp]
            if src_seg == dest_seg:
                continue  # same segment, not a cross-ref

            src_node_name = inp.rsplit("/", 1)[-1]
            results.append({
                "from_segment": src_seg,
                "from_node": src_node_name,
                "to_segment": dest_seg,
                "to_node": lm_node_name,
                "to_input_idx": idx,
                "data_hint": list(src_writes),
            })

    return results
