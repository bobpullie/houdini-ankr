"""Tests for cross_refs — cross-segment reference extraction."""
from ankr.cross_refs import extract_cross_segment_refs


def _make_enriched(*segments):
    """Helper: each segment is (seg_id, [(node_path, writes), ...])."""
    result = []
    for seg_id, nodes in segments:
        result.append({
            "seg_id": seg_id,
            "nodes": [
                {"path": path, "writes": writes}
                for path, writes in nodes
            ],
        })
    return result


def _make_landmarks(*landmarks):
    """Helper: each landmark is (lid, path, type_, kind, between)."""
    return [
        {"id": lid, "path": path, "type": type_, "kind": kind, "between": between}
        for lid, path, type_, kind, between in landmarks
    ]


def test_basic_cross_ref():
    """merge2 has input 1 from seg_01 node reaching seg_03, bypassing seg_02."""
    enriched = _make_enriched(
        ("seg_01_terrain", [
            ("/obj/H/terrain_out", ["height", "N"]),
        ]),
        ("seg_02_scatter", [
            ("/obj/H/scatter1", ["P"]),
        ]),
        ("seg_03_scatter", [
            ("/obj/H/merge2", ["P"]),
        ]),
    )
    landmark_records = _make_landmarks(
        ("M1", "/obj/H/merge2", "merge", "branch", "seg_02 → seg_03"),
    )
    landmark_inputs = {
        "/obj/H/merge2": ["/obj/H/scatter1", "/obj/H/terrain_out"],
    }

    refs = extract_cross_segment_refs(enriched, landmark_records, landmark_inputs)
    assert len(refs) == 1
    r = refs[0]
    assert r["from_segment"] == "seg_01_terrain"
    assert r["from_node"] == "terrain_out"
    assert r["to_segment"] == "seg_03_scatter"
    assert r["to_node"] == "merge2"
    assert r["to_input_idx"] == 1
    assert r["data_hint"] == ["height", "N"]


def test_no_cross_refs():
    """Single merge with one input — no cross-refs (input 0 is main chain)."""
    enriched = _make_enriched(
        ("seg_01_base", [
            ("/obj/H/node1", ["P"]),
        ]),
        ("seg_02_out", [
            ("/obj/H/merge1", ["P"]),
        ]),
    )
    landmark_records = _make_landmarks(
        ("M1", "/obj/H/merge1", "merge", "branch", "seg_01 → seg_02"),
    )
    landmark_inputs = {
        "/obj/H/merge1": ["/obj/H/node1"],
    }

    refs = extract_cross_segment_refs(enriched, landmark_records, landmark_inputs)
    assert refs == []


def test_external_input_ignored():
    """Input from a node not in any segment is skipped."""
    enriched = _make_enriched(
        ("seg_01_base", [
            ("/obj/H/node1", ["P"]),
        ]),
        ("seg_02_out", [
            ("/obj/H/merge1", ["P"]),
        ]),
    )
    landmark_records = _make_landmarks(
        ("M1", "/obj/H/merge1", "merge", "branch", "seg_01 → seg_02"),
    )
    landmark_inputs = {
        "/obj/H/merge1": ["/obj/H/node1", "/obj/EXTERNAL/unknown"],
    }

    refs = extract_cross_segment_refs(enriched, landmark_records, landmark_inputs)
    assert refs == []


def test_none_input_skipped():
    """None input slots are skipped."""
    enriched = _make_enriched(
        ("seg_01_base", [
            ("/obj/H/node1", ["P"]),
        ]),
        ("seg_02_out", [
            ("/obj/H/merge1", ["P"]),
        ]),
    )
    landmark_records = _make_landmarks(
        ("M1", "/obj/H/merge1", "merge", "branch", "seg_01 → seg_02"),
    )
    landmark_inputs = {
        "/obj/H/merge1": ["/obj/H/node1", None, None],
    }

    refs = extract_cross_segment_refs(enriched, landmark_records, landmark_inputs)
    assert refs == []


def test_multiple_cross_refs():
    """Two cross-refs from same merge node (inputs 1 and 2 from different segments)."""
    enriched = _make_enriched(
        ("seg_01_terrain", [
            ("/obj/H/terrain_out", ["height", "N"]),
        ]),
        ("seg_02_scatter", [
            ("/obj/H/scatter_out", ["P", "id"]),
        ]),
        ("seg_03_final", [
            ("/obj/H/merge3", ["P"]),
        ]),
    )
    landmark_records = _make_landmarks(
        ("M1", "/obj/H/merge3", "merge", "branch", "seg_02 → seg_03"),
    )
    landmark_inputs = {
        "/obj/H/merge3": ["/obj/H/scatter_out", "/obj/H/terrain_out", "/obj/H/scatter_out"],
    }

    refs = extract_cross_segment_refs(enriched, landmark_records, landmark_inputs)
    assert len(refs) == 2

    r1 = refs[0]
    assert r1["from_segment"] == "seg_01_terrain"
    assert r1["from_node"] == "terrain_out"
    assert r1["to_segment"] == "seg_03_final"
    assert r1["to_input_idx"] == 1
    assert r1["data_hint"] == ["height", "N"]

    r2 = refs[1]
    assert r2["from_segment"] == "seg_02_scatter"
    assert r2["from_node"] == "scatter_out"
    assert r2["to_segment"] == "seg_03_final"
    assert r2["to_input_idx"] == 2
    assert r2["data_hint"] == ["P", "id"]
