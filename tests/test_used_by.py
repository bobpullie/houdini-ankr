"""Tests for used_by inverse index + markdown rendering."""
from pathlib import Path
from ankr.manifest import Manifest, save_manifest
from ankr.used_by import (
    build_inverse_index,
    render_used_by_md,
    rebuild_used_by_for_manifest,
)


def _mk_manifest(hipname: str, nodes: dict) -> Manifest:
    m = Manifest(hipfile_name=hipname, hipfile_current=f"{hipname}.hip")
    for path, info in nodes.items():
        m.upsert_node(
            path=path,
            type_=info["type"],
            hash_=info.get("hash", "x"),
            referenced_by=info.get("referenced_by", []),
        )
        if "flags" in info:
            m.nodes[path]["flags"] = info["flags"]
    return m


def test_single_manifest_single_hda_single_reference():
    m = _mk_manifest("hipA", {
        "/obj/geo/sharp1": {
            "type": "bluei::KJI_SharpPoints_Bevel::1.2",
            "referenced_by": ["OUT_Curves/seg_03_bevel"],
        },
    })
    idx = build_inverse_index([m])
    refs = idx["bluei::KJI_SharpPoints_Bevel::1.2"]
    assert len(refs) == 1
    r = refs[0]
    assert r["hipname"] == "hipA"
    assert r["endnode"] == "OUT_Curves"
    assert r["segment"] == "seg_03_bevel"
    assert r["node_path"] == "/obj/geo/sharp1"
    assert r.get("bypass", False) is False


def test_node_referenced_by_multiple_segments_yields_multiple_entries():
    m = _mk_manifest("hipA", {
        "/obj/geo/sharp1": {
            "type": "bluei::X::1.0",
            "referenced_by": ["OUT_A/seg_01_a", "OUT_A/seg_02_b"],
        },
    })
    idx = build_inverse_index([m])
    assert len(idx["bluei::X::1.0"]) == 2


def test_multi_manifest_groups_same_hda_across_hips():
    m1 = _mk_manifest("hipA", {
        "/obj/a/n": {"type": "bluei::X::1.0", "referenced_by": ["OUT_A/seg_01"]},
    })
    m2 = _mk_manifest("hipB", {
        "/obj/b/n": {"type": "bluei::X::1.0", "referenced_by": ["OUT_B/seg_02"]},
    })
    idx = build_inverse_index([m1, m2])
    refs = idx["bluei::X::1.0"]
    assert sorted(r["hipname"] for r in refs) == ["hipA", "hipB"]


def test_bypass_flag_propagated():
    m = _mk_manifest("hipA", {
        "/obj/geo/sharp1": {
            "type": "bluei::X::1.0",
            "referenced_by": ["OUT_A/seg_01"],
            "flags": {"bypass": True},
        },
    })
    idx = build_inverse_index([m])
    assert idx["bluei::X::1.0"][0]["bypass"] is True


def test_builtin_node_types_also_indexed():
    m = _mk_manifest("hipA", {
        "/obj/geo/a": {"type": "attribwrangle", "referenced_by": ["OUT_A/seg_01"]},
    })
    idx = build_inverse_index([m])
    assert "attribwrangle" in idx


def test_render_empty_references_shows_no_usage():
    md = render_used_by_md("bluei::X::1.0", [])
    assert "bluei::X::1.0" in md
    assert "사용처 없음" in md


def test_render_groups_by_hipname_and_lists_segment():
    refs = [
        {"hipname": "hipA", "endnode": "OUT_A", "segment": "seg_01",
         "node_path": "/obj/a/n", "bypass": False},
        {"hipname": "hipB", "endnode": "OUT_B", "segment": "seg_02",
         "node_path": "/obj/b/n", "bypass": False},
    ]
    md = render_used_by_md("bluei::X::1.0", refs)
    assert "## hipA" in md
    assert "## hipB" in md
    assert "OUT_A" in md and "seg_01" in md
    assert "/obj/a/n" in md


def test_render_marks_bypass_with_warning():
    refs = [
        {"hipname": "hipA", "endnode": "OUT_A", "segment": "seg_01",
         "node_path": "/obj/a/n", "bypass": True},
    ]
    md = render_used_by_md("bluei::X::1.0", refs)
    assert "⚠️" in md


def _save_manifest_to(docs_root, hipname, manifest):
    target = docs_root / hipname / "manifest.yaml"
    save_manifest(manifest, target)
    return target


def test_rebuild_writes_used_by_for_each_hda_dep_in_current_manifest(tmp_path):
    m1 = _mk_manifest("hipA", {
        "/obj/a/n": {"type": "bluei::X::1.0", "referenced_by": ["OUT_A/seg_01"]},
    })
    m1.hda_dependencies = ["bluei::X::1.0"]
    _save_manifest_to(tmp_path, "hipA", m1)

    written = rebuild_used_by_for_manifest(tmp_path, m1)

    target = tmp_path / "custom_hda" / "bluei__X__1.0" / "used_by.md"
    assert target in written
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "bluei::X::1.0" in content
    assert "/obj/a/n" in content


def test_rebuild_aggregates_refs_across_all_manifests_in_docs_root(tmp_path):
    m1 = _mk_manifest("hipA", {
        "/obj/a/n": {"type": "bluei::X::1.0", "referenced_by": ["OUT_A/seg_01"]},
    })
    m1.hda_dependencies = ["bluei::X::1.0"]
    m2 = _mk_manifest("hipB", {
        "/obj/b/n": {"type": "bluei::X::1.0", "referenced_by": ["OUT_B/seg_02"]},
    })
    m2.hda_dependencies = ["bluei::X::1.0"]
    _save_manifest_to(tmp_path, "hipA", m1)
    _save_manifest_to(tmp_path, "hipB", m2)

    rebuild_used_by_for_manifest(tmp_path, m1)

    content = (tmp_path / "custom_hda" / "bluei__X__1.0" / "used_by.md").read_text(encoding="utf-8")
    assert "## hipA" in content
    assert "## hipB" in content


def test_rebuild_only_touches_hdas_listed_in_current_manifest_deps(tmp_path):
    m1 = _mk_manifest("hipA", {
        "/obj/a/n": {"type": "bluei::X::1.0", "referenced_by": ["OUT_A/seg_01"]},
        "/obj/a/m": {"type": "bluei::Y::1.0", "referenced_by": ["OUT_A/seg_02"]},
    })
    m1.hda_dependencies = ["bluei::X::1.0"]
    _save_manifest_to(tmp_path, "hipA", m1)

    written = rebuild_used_by_for_manifest(tmp_path, m1)

    assert (tmp_path / "custom_hda" / "bluei__X__1.0" / "used_by.md") in written
    assert not (tmp_path / "custom_hda" / "bluei__Y__1.0" / "used_by.md").exists()


def test_rebuild_used_by_ignores_hda_kind_manifests(tmp_path: Path):
    """Adding an HDA manifest under custom_hda/<safe>/manifest.yaml
    must NOT participate in the cross-hip used_by glob aggregation,
    since HDA-internal nodes are out of scope."""
    docs = tmp_path
    hip_m = Manifest(
        hipfile_name="HIP_X",
        hipfile_current="HIP_X.hip",
        kind="hip",
    )
    hip_m.upsert_node(
        "/obj/X/inst",
        "bluei::Foo::1.0",
        "h_inst",
        ["OUT_X/seg_01_inst"],
        flags={"bypass": False},
    )
    hip_m.add_hda_dependency("bluei::Foo::1.0")
    save_manifest(hip_m, docs / "HIP_X" / "manifest.yaml")

    hda_m = Manifest(
        hipfile_name="bluei::Foo::1.0",
        hipfile_current="bluei__Foo__1.0.hdalc",
        kind="hda",
        hda_type="bluei::Foo::1.0",
        internal_endnode="output0",
    )
    hda_m.upsert_node(
        "internal_nested_foo",
        "bluei::Foo::1.0",
        "h_x",
        ["internal/seg_01_nested"],
    )
    save_manifest(hda_m, docs / "custom_hda" / "bluei__Foo__1.0" / "manifest.yaml")

    rebuild_used_by_for_manifest(docs, hip_m)
    used_by_md = (docs / "custom_hda" / "bluei__Foo__1.0" / "used_by.md").read_text(
        encoding="utf-8"
    )
    assert "/obj/X/inst" in used_by_md
    assert "internal_nested_foo" not in used_by_md
