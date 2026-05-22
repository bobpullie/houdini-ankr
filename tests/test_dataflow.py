"""Tests for dataflow module — attribute/group lifecycle extraction."""
from ankr.dataflow import extract_attrib_lifecycle, render_dataflow_md


def _make_segments():
    """3 segments with attribute flow: seg_01 creates, seg_02 consumes, seg_03 deletes."""
    return [
        {
            "seg_id": "seg_01_init",
            "nodes": [
                {"name": "w1", "type": "attribwrangle", "kind": "wrangle",
                 "reads": [], "writes": ["foo", "bar"],
                 "groups_read": [], "groups_write": ["grpA"],
                 "vex_code": "f@foo = 1.0;\ni@bar = 2;",
                 "params_non_default": {}},
            ],
        },
        {
            "seg_id": "seg_02_process",
            "nodes": [
                {"name": "w2", "type": "attribwrangle", "kind": "wrangle",
                 "reads": ["foo"], "writes": ["baz"],
                 "groups_read": ["grpA"], "groups_write": [],
                 "vex_code": "f@baz = f@foo * 2;",
                 "params_non_default": {}},
            ],
        },
        {
            "seg_id": "seg_03_cleanup",
            "nodes": [
                {"name": "del1", "type": "attribdelete", "kind": "data_transform",
                 "reads": [], "writes": [],
                 "groups_read": [], "groups_write": [],
                 "vex_code": "",
                 "params_non_default": {"ptdel": "foo bar"}},
            ],
        },
    ]


def test_extract_attrib_lifecycle():
    segs = _make_segments()
    lifecycle = extract_attrib_lifecycle(segs)

    assert "foo" in lifecycle["attribs"]
    foo = lifecycle["attribs"]["foo"]
    assert foo["created_in"] == ["seg_01_init"]
    assert foo["consumed_in"] == ["seg_02_process"]
    assert foo["deleted_in"] == ["seg_03_cleanup"]

    assert "bar" in lifecycle["attribs"]
    bar = lifecycle["attribs"]["bar"]
    assert bar["created_in"] == ["seg_01_init"]
    assert bar["consumed_in"] == []
    assert bar["deleted_in"] == ["seg_03_cleanup"]


def test_extract_dead_attribs():
    segs = _make_segments()
    lifecycle = extract_attrib_lifecycle(segs)
    dead = [name for name, info in lifecycle["attribs"].items()
            if not info["consumed_in"]]
    assert "bar" in dead
    assert "foo" not in dead


def test_extract_group_lifecycle():
    segs = _make_segments()
    lifecycle = extract_attrib_lifecycle(segs)
    assert "grpA" in lifecycle["groups"]
    grpA = lifecycle["groups"]["grpA"]
    assert grpA["created_in"] == ["seg_01_init"]
    assert grpA["consumed_in"] == ["seg_02_process"]


def test_render_dataflow_md():
    segs = _make_segments()
    lifecycle = extract_attrib_lifecycle(segs)
    md = render_dataflow_md(lifecycle, endnode="/obj/Test/OUT")
    assert "## 어트리뷰트 흐름" in md
    assert "foo" in md
    assert "## Dead Attribute 경고" in md
    assert "bar" in md
    assert "## 그룹 흐름" in md
