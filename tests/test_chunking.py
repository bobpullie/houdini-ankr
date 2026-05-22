"""Tests for chunking module."""
from ankr.chunking import (
    is_landmark_type,
    is_branch_type,
    is_block_boundary_type,
    split_segments,
)


def test_merge_is_landmark():
    assert is_landmark_type("merge") is True


def test_switch_is_landmark():
    assert is_landmark_type("switch") is True


def test_copy_to_points_is_landmark():
    assert is_landmark_type("copytopoints") is True


def test_object_merge_is_landmark():
    assert is_landmark_type("object_merge") is True
    assert is_landmark_type("objectmerge") is True


def test_foreach_begin_is_landmark():
    assert is_landmark_type("block_begin") is True
    assert is_landmark_type("block_end") is True


def test_normal_node_not_landmark():
    assert is_landmark_type("attribwrangle") is False
    assert is_landmark_type("transform") is False
    assert is_landmark_type("scatter") is False


def test_branch_vs_block_distinction():
    assert is_branch_type("merge") is True
    assert is_branch_type("switch") is True
    assert is_branch_type("block_begin") is False
    assert is_block_boundary_type("block_begin") is True
    assert is_block_boundary_type("block_end") is True
    assert is_block_boundary_type("merge") is False


def _node(name, type_):
    return {"name": name, "type": type_}


def test_short_chain_single_segment():
    nodes = [_node(f"n{i}", "transform") for i in range(5)]
    segs = split_segments(nodes)
    assert len(segs) == 1
    assert len(segs[0]) == 5


def test_long_chain_split_at_n20():
    nodes = [_node(f"n{i}", "transform") for i in range(50)]
    segs = split_segments(nodes)
    assert len(segs) >= 3
    assert all(len(s) <= 20 for s in segs)


def test_split_at_wrangle_3_rule():
    nodes = []
    for i in range(8):
        t = "attribwrangle" if i in (1, 3, 5, 7) else "transform"
        nodes.append(_node(f"n{i}", t))
    segs = split_segments(nodes)
    assert len(segs) >= 2
    for s in segs:
        wcount = sum(1 for n in s if "wrangle" in n["type"].lower())
        assert wcount <= 3


def test_branch_node_starts_new_segment():
    nodes = [
        _node("a", "transform"),
        _node("b", "transform"),
        _node("M1", "merge"),
        _node("c", "transform"),
        _node("d", "transform"),
        _node("SW1", "switch"),
        _node("e", "transform"),
    ]
    segs = split_segments(nodes)
    assert len(segs) == 3
    assert [n["name"] for n in segs[0]] == ["a", "b"]
    assert [n["name"] for n in segs[1]] == ["c", "d"]
    assert [n["name"] for n in segs[2]] == ["e"]


def test_branch_at_start():
    nodes = [
        _node("M1", "merge"),
        _node("a", "transform"),
        _node("b", "transform"),
    ]
    segs = split_segments(nodes)
    assert len(segs) == 1
    assert [n["name"] for n in segs[0]] == ["a", "b"]


def test_branch_at_end():
    nodes = [
        _node("a", "transform"),
        _node("b", "transform"),
        _node("M1", "merge"),
    ]
    segs = split_segments(nodes)
    assert len(segs) == 1
    assert [n["name"] for n in segs[0]] == ["a", "b"]
