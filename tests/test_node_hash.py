"""Tests for node hash computation."""

from ankr.node_hash import canonical_serialize, compute_node_hash


def test_same_input_same_hash():
    info = {
        "params": {"seed": 42, "scale": 1.5},
        "vex_code": "",
        "flags": {"bypass": False},
        "seed_values": {"seed": 42},
    }
    h1 = compute_node_hash(info)
    h2 = compute_node_hash(info)
    assert h1 == h2


def test_param_value_change_changes_hash():
    base = {"params": {"seed": 42}, "vex_code": "", "flags": {}, "seed_values": {"seed": 42}}
    other = {"params": {"seed": 43}, "vex_code": "", "flags": {}, "seed_values": {"seed": 43}}
    assert compute_node_hash(base) != compute_node_hash(other)


def test_param_order_independent():
    a = {"params": {"a": 1, "b": 2}, "vex_code": "", "flags": {}, "seed_values": {}}
    b = {"params": {"b": 2, "a": 1}, "vex_code": "", "flags": {}, "seed_values": {}}
    assert compute_node_hash(a) == compute_node_hash(b)


def test_flag_change_changes_hash():
    base = {"params": {}, "vex_code": "", "flags": {"bypass": False}, "seed_values": {}}
    bypassed = {"params": {}, "vex_code": "", "flags": {"bypass": True}, "seed_values": {}}
    assert compute_node_hash(base) != compute_node_hash(bypassed)


def test_vex_code_change_changes_hash():
    a = {"params": {}, "vex_code": "@density = 1.0;", "flags": {}, "seed_values": {}}
    b = {"params": {}, "vex_code": "@density = 2.0;", "flags": {}, "seed_values": {}}
    assert compute_node_hash(a) != compute_node_hash(b)


def test_dynamic_expression_uses_expression_string():
    a = {
        "params": {"frame": {"_expression": "$F"}},
        "vex_code": "", "flags": {}, "seed_values": {},
    }
    b = {
        "params": {"frame": {"_expression": "$F"}},
        "vex_code": "", "flags": {}, "seed_values": {},
    }
    assert compute_node_hash(a) == compute_node_hash(b)
    c = {
        "params": {"frame": {"_expression": "$F + 1"}},
        "vex_code": "", "flags": {}, "seed_values": {},
    }
    assert compute_node_hash(a) != compute_node_hash(c)


def test_canonical_serialize_is_deterministic():
    info = {
        "params": {"z": 3, "a": 1, "m": 2},
        "vex_code": "x",
        "flags": {"y": True, "x": False},
        "seed_values": {},
    }
    s1 = canonical_serialize(info)
    s2 = canonical_serialize(info)
    assert s1 == s2
    assert s1.index('"a"') < s1.index('"m"') < s1.index('"z"')


def test_hash_format():
    info = {"params": {}, "vex_code": "", "flags": {}, "seed_values": {}}
    h = compute_node_hash(info)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
