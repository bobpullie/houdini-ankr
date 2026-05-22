"""Tests for external reference extraction from object_merge landmarks."""


def test_extract_external_refs_basic():
    """object_merge with objpath1 pointing outside the chain → external ref."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/merge1", "type": "object_merge",
         "kind": "branch", "between": "seg_01 → seg_02"},
    ]
    objpath1_by_landmark = {
        "/obj/H/merge1": "/obj/TERRAIN/OUT_terrain",
    }
    chain_paths = {"/obj/H/node1", "/obj/H/node2", "/obj/H/merge1"}

    refs = extract_external_refs(landmark_records, objpath1_by_landmark, chain_paths)

    assert len(refs) == 1
    assert refs[0]["landmark_id"] == "M1"
    assert refs[0]["landmark_path"] == "/obj/H/merge1"
    assert refs[0]["source_path"] == "/obj/TERRAIN/OUT_terrain"
    assert refs[0]["between"] == "seg_01 → seg_02"


def test_extract_external_refs_internal_source():
    """object_merge referencing a node inside the chain → NOT external."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/merge1", "type": "object_merge",
         "kind": "branch", "between": "seg_01 → seg_02"},
    ]
    objpath1_by_landmark = {"/obj/H/merge1": "/obj/H/node1"}
    chain_paths = {"/obj/H/node1", "/obj/H/merge1"}

    refs = extract_external_refs(landmark_records, objpath1_by_landmark, chain_paths)
    assert refs == []


def test_extract_external_refs_non_object_merge():
    """Non-object_merge landmarks are skipped."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/merge1", "type": "merge",
         "kind": "branch", "between": "seg_01 → seg_02"},
    ]
    objpath1_by_landmark = {"/obj/H/merge1": "/obj/TERRAIN/OUT"}
    chain_paths = {"/obj/H/node1"}

    refs = extract_external_refs(landmark_records, objpath1_by_landmark, chain_paths)
    assert refs == []


def test_extract_external_refs_empty_objpath1():
    """object_merge with empty objpath1 → no external ref."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/merge1", "type": "object_merge",
         "kind": "branch", "between": "seg_01 → seg_02"},
    ]
    objpath1_by_landmark = {"/obj/H/merge1": ""}
    chain_paths = set()

    refs = extract_external_refs(landmark_records, objpath1_by_landmark, chain_paths)
    assert refs == []


def test_extract_external_refs_multiple():
    """Multiple object_merge landmarks, some external some internal."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/om1", "type": "object_merge",
         "kind": "branch", "between": "(src) → seg_01"},
        {"id": "M2", "path": "/obj/H/om2", "type": "object_merge",
         "kind": "branch", "between": "seg_01 → seg_02"},
    ]
    objpath1_by_landmark = {
        "/obj/H/om1": "/obj/TERRAIN/OUT",
        "/obj/H/om2": "/obj/H/node_a",
    }
    chain_paths = {"/obj/H/om1", "/obj/H/om2", "/obj/H/node_a"}

    refs = extract_external_refs(landmark_records, objpath1_by_landmark, chain_paths)
    assert len(refs) == 1
    assert refs[0]["landmark_id"] == "M1"
    assert refs[0]["source_path"] == "/obj/TERRAIN/OUT"


def test_skeleton_md_renders_external_refs():
    """render_skeleton_md includes 외부 참조 table when external_refs present."""
    from ankr.markdown_gen import render_skeleton_md

    skeleton = {
        "endnode": "/obj/H/OUT",
        "hipfile_current": "test.hiplc",
        "last_sync": "2026-04-13",
        "node_count_total": 5,
        "landmark_count": 1,
        "segment_count": 2,
        "random_seeds_in_use": [],
        "flag_anomalies": [],
        "unresolved_issues": [],
        "hda_dependencies": [],
        "landmarks": [],
        "segments_index": [],
        "graph_nodes": {"SRC": {"label": "(src)", "shape": "rect"},
                        "OUT": {"label": "OUT", "shape": "rect"}},
        "graph_edges": [{"from": "SRC", "to": "OUT"}],
        "external_refs": [
            {
                "landmark_id": "M1",
                "landmark_path": "/obj/H/merge1",
                "source_path": "/obj/TERRAIN/OUT_terrain",
                "between": "seg_01 → seg_02",
            },
        ],
    }

    md = render_skeleton_md(skeleton)
    assert "## 외부 참조" in md
    assert "M1" in md
    assert "/obj/TERRAIN/OUT_terrain" in md


def test_skeleton_md_no_external_refs():
    """render_skeleton_md omits 외부 참조 section when empty."""
    from ankr.markdown_gen import render_skeleton_md

    skeleton = {
        "endnode": "/obj/H/OUT",
        "hipfile_current": "test.hiplc",
        "last_sync": "2026-04-13",
        "node_count_total": 5,
        "landmark_count": 0,
        "segment_count": 1,
        "random_seeds_in_use": [],
        "flag_anomalies": [],
        "unresolved_issues": [],
        "hda_dependencies": [],
        "landmarks": [],
        "segments_index": [],
        "graph_nodes": {"SRC": {"label": "(src)", "shape": "rect"},
                        "OUT": {"label": "OUT", "shape": "rect"}},
        "graph_edges": [{"from": "SRC", "to": "OUT"}],
    }

    md = render_skeleton_md(skeleton)
    assert "## 외부 참조" not in md


def test_extract_external_refs_objectmerge_variant():
    """'objectmerge' (no underscore) should also be detected."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/om1", "type": "objectmerge",
         "kind": "branch", "between": "seg_01 → seg_02"},
    ]
    objpath1_by_landmark = {"/obj/H/om1": "/obj/EXT/node"}
    chain_paths = {"/obj/H/om1"}

    refs = extract_external_refs(landmark_records, objpath1_by_landmark, chain_paths)
    assert len(refs) == 1
    assert refs[0]["source_path"] == "/obj/EXT/node"


def test_extract_external_refs_missing_landmark():
    """Landmark not in objpath1_by_landmark → no crash, no ref."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/om1", "type": "object_merge",
         "kind": "branch", "between": ""},
    ]
    refs = extract_external_refs(landmark_records, {}, set())
    assert refs == []


def test_extract_external_refs_no_between_field():
    """Landmark without 'between' field should not crash."""
    from ankr.hou_runtime import extract_external_refs

    landmark_records = [
        {"id": "M1", "path": "/obj/H/om1", "type": "object_merge", "kind": "branch"},
    ]
    objpath1_by_landmark = {"/obj/H/om1": "/obj/EXT/src"}
    refs = extract_external_refs(landmark_records, objpath1_by_landmark, set())
    assert len(refs) == 1
    assert refs[0]["between"] == ""


def test_skeleton_md_multiple_external_refs():
    """Multiple external refs render as table rows."""
    from ankr.markdown_gen import render_skeleton_md

    skeleton = {
        "endnode": "/obj/H/OUT",
        "hipfile_current": "test.hiplc",
        "last_sync": "2026-04-13",
        "node_count_total": 5,
        "landmark_count": 2,
        "segment_count": 2,
        "random_seeds_in_use": [],
        "flag_anomalies": [],
        "unresolved_issues": [],
        "hda_dependencies": [],
        "landmarks": [],
        "segments_index": [],
        "graph_nodes": {"SRC": {"label": "(src)", "shape": "rect"},
                        "OUT": {"label": "OUT", "shape": "rect"}},
        "graph_edges": [{"from": "SRC", "to": "OUT"}],
        "external_refs": [
            {"landmark_id": "M1", "landmark_path": "/obj/H/om1",
             "source_path": "/obj/A/OUT", "between": "seg_01 → seg_02"},
            {"landmark_id": "M3", "landmark_path": "/obj/H/om2",
             "source_path": "/obj/B/OUT", "between": "seg_03 → seg_04"},
        ],
    }

    md = render_skeleton_md(skeleton)
    assert md.count("M1") >= 1
    assert md.count("M3") >= 1
    assert "/obj/A/OUT" in md
    assert "/obj/B/OUT" in md
