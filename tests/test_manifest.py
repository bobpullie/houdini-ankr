"""Tests for manifest read/write."""
from pathlib import Path
from ankr.manifest import (
    Manifest, load_manifest, save_manifest,
)


def test_create_empty_manifest():
    m = Manifest(hipfile_name="KJI_Kr_House", hipfile_current="KJI_Kr_House_v023.hip")
    assert m.hipfile_name == "KJI_Kr_House"
    assert m.endnodes == []
    assert m.nodes == {}
    assert m.hda_dependencies == []


def test_save_and_load_roundtrip(tmp_path: Path):
    m = Manifest(
        hipfile_name="KJI_Kr_House",
        hipfile_current="KJI_Kr_House_v023.hip",
        hipfile_path="/test/projects/KJI_Kr_House_v023.hip",
        houdini_version="21.0.596",
    )
    m.add_endnode(
        name="OUT_houses",
        path="/obj/KJI_Kr_House/OUT_houses",
        skeleton="OUT_houses/skeleton.md",
    )
    m.upsert_node(
        path="/obj/KJI_Kr_House/scatter_houses",
        type_="scatter",
        hash_="a3f8c1",
        referenced_by=["OUT_houses/seg_05"],
    )
    m.add_hda_dependency("kji::village_split::1.0")

    target = tmp_path / "manifest.yaml"
    save_manifest(m, target)

    loaded = load_manifest(target)
    assert loaded.hipfile_name == "KJI_Kr_House"
    assert len(loaded.endnodes) == 1
    assert loaded.endnodes[0]["name"] == "OUT_houses"
    assert "/obj/KJI_Kr_House/scatter_houses" in loaded.nodes
    assert loaded.nodes["/obj/KJI_Kr_House/scatter_houses"]["hash"] == "a3f8c1"
    assert "kji::village_split::1.0" in loaded.hda_dependencies


def test_upsert_existing_node_replaces_hash(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/n", "transform", "abc123", ["seg_01"])
    m.upsert_node("/obj/n", "transform", "def456", ["seg_01", "seg_02"])
    assert m.nodes["/obj/n"]["hash"] == "def456"
    assert "seg_02" in m.nodes["/obj/n"]["referenced_by"]


def test_upsert_with_flags_persists_through_roundtrip(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/n", "bluei::X::1.0", "h1", ["OUT_x/seg_01"],
                  flags={"bypass": True, "display": False})
    assert m.nodes["/obj/n"]["flags"]["bypass"] is True

    target = tmp_path / "manifest.yaml"
    save_manifest(m, target)
    loaded = load_manifest(target)
    assert loaded.nodes["/obj/n"]["flags"]["bypass"] is True
    assert loaded.nodes["/obj/n"]["flags"]["display"] is False


def test_upsert_without_flags_keeps_empty_flags(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/n", "transform", "h1", ["seg_01"])
    assert m.nodes["/obj/n"].get("flags", {}) == {}


def test_diff_detects_flag_change(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/n", "transform", "h1", ["OUT_x/seg_01"], flags={"bypass": False})

    diff = m.diff_against_current({"/obj/n": "h1"}, current_flags={"/obj/n": {"bypass": True}})
    assert "/obj/n" in diff["changed"]


def test_load_missing_file_returns_none(tmp_path: Path):
    p = tmp_path / "nope.yaml"
    assert load_manifest(p) is None


def test_diff_against_current_returns_changed_nodes(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/a", "transform", "h_old_a", ["seg_01"])
    m.upsert_node("/obj/b", "transform", "h_old_b", ["seg_02"])
    m.upsert_node("/obj/c", "transform", "h_old_c", ["seg_03"])

    current = {
        "/obj/a": "h_old_a",
        "/obj/b": "h_NEW_b",
        "/obj/d": "h_NEW_d",
    }
    diff = m.diff_against_current(current)
    assert "/obj/b" in diff["changed"]
    assert "/obj/c" in diff["deleted"]
    assert "/obj/d" in diff["added"]
    assert "/obj/a" not in diff["changed"]


def test_affected_segments_for_changes(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/a", "transform", "h1", ["OUT_x/seg_01"])
    m.upsert_node("/obj/b", "transform", "h2", ["OUT_x/seg_02", "OUT_y/seg_01"])

    current = {"/obj/a": "h1_changed", "/obj/b": "h2_changed"}
    diff = m.diff_against_current(current)
    affected = m.affected_segments(diff)
    assert "OUT_x/seg_01" in affected
    assert "OUT_x/seg_02" in affected
    assert "OUT_y/seg_01" in affected


def test_diff_restrict_to_endnode_ignores_other_endnode_nodes():
    """When syncing one endnode, nodes belonging only to OTHER endnodes
    must NOT appear as 'deleted' just because they're absent from the
    current chain hashes (which were extracted for a single endnode)."""
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/x_only", "transform", "h_x", ["OUT_x/seg_01"])
    m.upsert_node("/obj/y_only", "transform", "h_y", ["OUT_y/seg_01"])
    m.upsert_node("/obj/shared", "transform", "h_s", ["OUT_x/seg_02", "OUT_y/seg_02"])

    current = {
        "/obj/x_only": "h_x",
        "/obj/shared": "h_s_NEW",
    }
    diff = m.diff_against_current(current, restrict_to_endnode="OUT_x")
    assert diff["changed"] == ["/obj/shared"]
    assert diff["deleted"] == []
    assert diff["added"] == []


def test_diff_restrict_to_endnode_detects_actual_deletion():
    """A node belonging to the target endnode that's missing from
    current_hashes should still be marked deleted."""
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/a", "transform", "h_a", ["OUT_x/seg_01"])
    m.upsert_node("/obj/removed", "transform", "h_r", ["OUT_x/seg_02"])

    current = {"/obj/a": "h_a"}
    diff = m.diff_against_current(current, restrict_to_endnode="OUT_x")
    assert "/obj/removed" in diff["deleted"]


def test_diff_restrict_to_endnode_handles_shared_node_with_only_other_ref():
    """A node referenced ONLY by other endnodes shouldn't be in scope at all."""
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    m.upsert_node("/obj/y_node", "transform", "h_y", ["OUT_y/seg_01"])

    current = {"/obj/y_node": "h_y_NEW"}
    diff = m.diff_against_current(current, restrict_to_endnode="OUT_x")
    assert diff["changed"] == []
    assert diff["added"] == []


def test_kind_field_defaults_to_hip():
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    assert m.kind == "hip"


def test_hda_manifest_roundtrip_preserves_modification_time(tmp_path: Path):
    m = Manifest(
        hipfile_name="bluei::KJI_SharpPoints_Bevel::1.2",
        hipfile_current="sop_bluei.KJI_SharpPoints_Bevel.1.2.hdalc",
        hipfile_path="/test/hda/sop_bluei.KJI_SharpPoints_Bevel.1.2.hdalc",
        houdini_version="21.0.671",
        kind="hda",
        hda_type="bluei::KJI_SharpPoints_Bevel::1.2",
        hda_modification_time=1696789012.345,
        internal_endnode="output0",
        internal_segments=[
            {"id": "seg_01_KJI_Find_sharp_Points", "node_count": 4},
        ],
        nested_hdas=[],
    )
    m.upsert_node(
        "KJI_Find_sharp_Points",
        "attribwrangle",
        "h_kfsp",
        ["internal/seg_01_KJI_Find_sharp_Points"],
        flags={"bypass": False, "lock": False, "template": False,
               "display": False, "render": False},
    )
    target = tmp_path / "manifest.yaml"
    save_manifest(m, target)

    loaded = load_manifest(target)
    assert loaded.kind == "hda"
    assert loaded.hda_type == "bluei::KJI_SharpPoints_Bevel::1.2"
    assert loaded.hda_modification_time == 1696789012.345
    assert loaded.internal_endnode == "output0"
    assert loaded.internal_segments == [
        {"id": "seg_01_KJI_Find_sharp_Points", "node_count": 4},
    ]
    assert loaded.nested_hdas == []
    assert "KJI_Find_sharp_Points" in loaded.nodes
    assert loaded.nodes["KJI_Find_sharp_Points"]["referenced_by"] == [
        "internal/seg_01_KJI_Find_sharp_Points"
    ]


def test_legacy_hip_manifest_without_kind_loads_as_hip(tmp_path: Path):
    """An older manifest.yaml on disk that predates the kind field must
    still load and report kind=='hip'."""
    legacy_yaml = """\
hipfile_name: KJI_X
hipfile_current: KJI_X_v001.hip
last_sync: 2026-04-01T00:00
houdini_version: 21.0.0
endnodes:
- name: OUT_X
  path: /obj/X/OUT_X
  skeleton: OUT_X/skeleton.md
  node_count: 5
  landmark_count: 0
  segment_count: 1
  last_sync: 2026-04-01T00:00
nodes:
  /obj/X/transform1:
    hash: abc
    type: xform
    referenced_by:
    - OUT_X/seg_01_transform1
hda_dependencies: []
"""
    target = tmp_path / "manifest.yaml"
    target.write_text(legacy_yaml, encoding="utf-8")
    m = load_manifest(target)
    assert m is not None
    assert m.kind == "hip"
    assert m.hda_type == ""
    assert m.hda_modification_time == 0.0
    assert m.internal_segments == []
    assert m.endnodes[0]["name"] == "OUT_X"


def test_hda_manifest_roundtrip_preserves_spare_parameters_schema(tmp_path: Path):
    """HDA spare parm interface persists through save/load."""
    schema = [
        {"name": "angle_threshold", "label": "Angle Threshold",
         "type": "Float", "num_components": 1, "default": [30.0]},
        {"name": "bevel_offset", "label": "Bevel Offset",
         "type": "Float", "num_components": 1, "default": [0.05]},
        {"name": "bevelPointsGrp", "label": "Output Bevel Points Group",
         "type": "Toggle", "num_components": 1, "default": 0},
    ]
    m = Manifest(
        hipfile_name="bluei::KJI_Test::1.0",
        hipfile_current="sop_bluei.KJI_Test.1.0.hdalc",
        kind="hda",
        hda_type="bluei::KJI_Test::1.0",
        spare_parameters_schema=schema,
    )
    target = tmp_path / "manifest.yaml"
    save_manifest(m, target)

    loaded = load_manifest(target)
    assert loaded.spare_parameters_schema == schema
    assert loaded.spare_parameters_schema[0]["name"] == "angle_threshold"
    assert loaded.spare_parameters_schema[2]["type"] == "Toggle"


def test_legacy_manifest_without_spare_parameters_schema_loads_empty(tmp_path: Path):
    """Backward compat: pre-O2 manifests must still load with empty schema."""
    legacy_yaml = """\
hipfile_name: legacy
hipfile_current: legacy.hip
kind: hip
endnodes: []
nodes: {}
hda_dependencies: []
"""
    target = tmp_path / "manifest.yaml"
    target.write_text(legacy_yaml, encoding="utf-8")
    m = load_manifest(target)
    assert m is not None
    assert m.spare_parameters_schema == []


def test_previous_sync_default_none():
    m = Manifest(hipfile_name="X", hipfile_current="X.hip")
    assert m.previous_sync is None


def test_previous_sync_save_load_roundtrip(tmp_path: Path):
    m = Manifest(hipfile_name="X", hipfile_current="X.hip",
                 last_sync="2026-04-09T14:00", previous_sync="2026-04-09T11:00")
    target = tmp_path / "manifest.yaml"
    save_manifest(m, target)
    loaded = load_manifest(target)
    assert loaded.previous_sync == "2026-04-09T11:00"
    assert loaded.last_sync == "2026-04-09T14:00"


def test_previous_sync_missing_in_legacy_yaml(tmp_path: Path):
    """Existing manifests without previous_sync should load as None."""
    legacy = {"hipfile_name": "X", "hipfile_current": "X.hip",
              "last_sync": "2026-04-09T14:00", "endnodes": [], "nodes": {},
              "hda_dependencies": [], "kind": "hip"}
    target = tmp_path / "manifest.yaml"
    import yaml
    with open(target, "w") as f:
        yaml.safe_dump(legacy, f)
    loaded = load_manifest(target)
    assert loaded.previous_sync is None


def test_manifest_roundtrip_preserves_segment_summary(tmp_path):
    m = Manifest(hipfile_name="h", hipfile_current="h.hip")
    m.segment_summary = [
        {"seg_id": "seg_01_a", "nodes": 5, "wrangles": 1, "vex_lines": 42,
         "split": 0, "file_kb": 4.2},
    ]
    path = tmp_path / "manifest.yaml"
    save_manifest(m, path)
    loaded = load_manifest(path)
    assert loaded.segment_summary == m.segment_summary
