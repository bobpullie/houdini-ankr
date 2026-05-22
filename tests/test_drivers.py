"""Tests for the hip-target driver layer (first_track / sync_endnode).

P1.6 Wave 4 scope: hip-only. HDA driver tests (first_track_hda / sync_hda)
will arrive with T4 alongside the `_hda` driver port.

Pure-python — no Houdini dependency. Inputs are data dicts that the runtime
layer (hou_runtime) would normally produce.
"""
from __future__ import annotations
from pathlib import Path

import yaml

from ankr.drivers import first_track, sync_endnode
from ankr.manifest import load_manifest
from ankr.drivers._helpers import compute_segment_meta


# ---------- Fixture builders ----------

def _hip_meta() -> dict:
    return {
        "hipfile_current": "TEST_HIP_001.hiplc",
        "hipfile_path": "X:/TEST/TEST_HIP_001.hiplc",
        "houdini_version": "21.0.671",
    }


def _simple_chain() -> list[dict]:
    """2-node linear chain (HDA → null) — analog of OUT_KH_TERRAIN."""
    return [
        {
            "name": "kh_terrain", "type": "blueitems::KH_Terrain::1.0",
            "path": "/obj/KH_terrain/kh_terrain", "is_hda": True,
            "hda_type": "blueitems::KH_Terrain::1.0",
        },
        {
            "name": "OUT_KH", "type": "null", "path": "/obj/KH_terrain/OUT_KH",
            "is_hda": False, "hda_type": "",
        },
    ]


def _simple_enriched() -> list[dict]:
    return [{
        "seg_id": "seg_01_kh_terrain",
        "nodes": [
            {
                "name": "kh_terrain", "type": "blueitems::KH_Terrain::1.0",
                "path": "/obj/KH_terrain/kh_terrain", "is_hda": True,
                "hda_type": "blueitems::KH_Terrain::1.0",
                "kind": "data_transform", "flags": {},
                "params_non_default": {}, "random_seeds": [],
            },
            {
                "name": "OUT_KH", "type": "null",
                "path": "/obj/KH_terrain/OUT_KH", "is_hda": False,
                "kind": "passthrough", "flags": {},
                "params_non_default": {}, "random_seeds": [],
            },
        ],
    }]


def _simple_narratives() -> dict:
    return {
        "seg_01_kh_terrain": {
            "data": {"purpose": "test purpose"},
            "narrative": "테스트 세그먼트 설명.",
        },
    }


def _simple_hwf() -> dict:
    """compute_hashes_and_flags_for_paths shape."""
    return {
        "/obj/KH_terrain/kh_terrain": {
            "hash": "h_kh", "flags": {"bypass": False, "lock": False,
                                       "template": False, "display": True,
                                       "render": True},
        },
        "/obj/KH_terrain/OUT_KH": {
            "hash": "h_out", "flags": {"bypass": False, "lock": False,
                                        "template": False, "display": False,
                                        "render": False},
        },
    }


# ---------- first_track tests ----------

def test_first_track_creates_manifest_when_absent(tmp_path: Path):
    docs = tmp_path / "docs"
    result = first_track(
        endnode_path="/obj/KH_terrain/OUT_KH",
        endnode_name="OUT_KH",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=_simple_chain(),
        enriched=_simple_enriched(),
        narratives=_simple_narratives(),
        hashes_with_flags=_simple_hwf(),
        docs_root=docs,
    )
    assert result["manifest_mode"] == "create"
    manifest = load_manifest(docs / "TEST_HIP" / "manifest.yaml")
    assert manifest is not None
    assert len(manifest.endnodes) == 1
    assert manifest.endnodes[0]["name"] == "OUT_KH"
    assert len(manifest.nodes) == 2
    assert manifest.nodes["/obj/KH_terrain/kh_terrain"]["flags"]["display"] is True
    assert "blueitems::KH_Terrain::1.0" in manifest.hda_dependencies
    assert (docs / "TEST_HIP" / "OUT_KH" / "skeleton.md").exists()
    assert (docs / "TEST_HIP" / "OUT_KH" / "segments" / "seg_01_kh_terrain.md").exists()
    assert (docs / "custom_hda" / "blueitems__KH_Terrain__1.0" / "used_by.md").exists()


def test_first_track_upserts_into_existing_manifest(tmp_path: Path):
    """Adding a 2nd endnode to an existing manifest must NOT clobber the
    first endnode's data — this is the defect found in temp/render_first_track.py.
    """
    docs = tmp_path / "docs"
    first_track(
        endnode_path="/obj/A/OUT_A",
        endnode_name="OUT_A",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=[{"name": "A_node", "type": "transform",
                "path": "/obj/A/A_node", "is_hda": False, "hda_type": ""}],
        enriched=[{
            "seg_id": "seg_01_a_node",
            "nodes": [{"name": "A_node", "type": "transform",
                       "path": "/obj/A/A_node", "is_hda": False,
                       "kind": "data_transform", "flags": {},
                       "params_non_default": {}, "random_seeds": []}],
        }],
        narratives={"seg_01_a_node": {"data": {}, "narrative": "A's job"}},
        hashes_with_flags={
            "/obj/A/A_node": {"hash": "h_a", "flags": {"bypass": False,
                "lock": False, "template": False, "display": True, "render": True}},
        },
        docs_root=docs,
    )
    result = first_track(
        endnode_path="/obj/KH_terrain/OUT_KH",
        endnode_name="OUT_KH",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=_simple_chain(),
        enriched=_simple_enriched(),
        narratives=_simple_narratives(),
        hashes_with_flags=_simple_hwf(),
        docs_root=docs,
    )
    assert result["manifest_mode"] == "upsert"
    manifest = load_manifest(docs / "TEST_HIP" / "manifest.yaml")
    endnode_names = {e["name"] for e in manifest.endnodes}
    assert endnode_names == {"OUT_A", "OUT_KH"}
    assert "/obj/A/A_node" in manifest.nodes
    assert "/obj/KH_terrain/kh_terrain" in manifest.nodes
    assert (docs / "TEST_HIP" / "OUT_A" / "skeleton.md").exists()
    assert (docs / "TEST_HIP" / "OUT_KH" / "skeleton.md").exists()


def test_first_track_returns_commit_bundle_with_used_by_files(tmp_path: Path):
    docs = tmp_path / "docs"
    result = first_track(
        endnode_path="/obj/KH_terrain/OUT_KH",
        endnode_name="OUT_KH",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=_simple_chain(),
        enriched=_simple_enriched(),
        narratives=_simple_narratives(),
        hashes_with_flags=_simple_hwf(),
        docs_root=docs,
    )
    bundle = result["commit_bundle"]
    assert bundle["message"].startswith("first track: TEST_HIP OUT_KH")
    assert any("TEST_HIP/" in p or "TEST_HIP\\" in p for p in bundle["paths"])
    assert any("blueitems__KH_Terrain__1.0" in p for p in bundle["paths"])


def test_first_track_passes_through_landmark_branches(tmp_path: Path):
    """Chain with a merge landmark and 2 segments around it must produce
    1 landmark + 2 segment files."""
    chain = [
        {"name": "src1", "type": "transform", "path": "/obj/x/src1",
         "is_hda": False, "hda_type": ""},
        {"name": "merge1", "type": "merge", "path": "/obj/x/merge1",
         "is_hda": False, "hda_type": ""},
        {"name": "post1", "type": "transform", "path": "/obj/x/post1",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [
        {"seg_id": "seg_01_src1", "nodes": [
            {"name": "src1", "type": "transform", "path": "/obj/x/src1",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
        {"seg_id": "seg_02_post1", "nodes": [
            {"name": "post1", "type": "transform", "path": "/obj/x/post1",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
    ]
    narratives = {
        "seg_01_src1": {"data": {}, "narrative": "first"},
        "seg_02_post1": {"data": {}, "narrative": "second"},
    }
    hwf = {
        "/obj/x/src1": {"hash": "h1", "flags": {}},
        "/obj/x/merge1": {"hash": "h2", "flags": {}},
        "/obj/x/post1": {"hash": "h3", "flags": {}},
    }
    docs = tmp_path / "docs"
    first_track(
        endnode_path="/obj/x/post1",
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=chain,
        enriched=enriched,
        narratives=narratives,
        hashes_with_flags=hwf,
        docs_root=docs,
    )
    skel = (docs / "TEST_HIP" / "OUT_X" / "skeleton.md").read_text(encoding="utf-8")
    assert "merge1" in skel
    assert (docs / "TEST_HIP" / "OUT_X" / "segments" / "seg_01_src1.md").exists()
    assert (docs / "TEST_HIP" / "OUT_X" / "segments" / "seg_02_post1.md").exists()


# ---------- sync_endnode tests ----------

def test_sync_endnode_only_re_renders_changed_segments(tmp_path: Path):
    """A sync that detects 1 changed node should re-render exactly 1 segment."""
    docs = tmp_path / "docs"
    chain = [
        {"name": "a", "type": "transform", "path": "/obj/x/a",
         "is_hda": False, "hda_type": ""},
        {"name": "merge1", "type": "merge", "path": "/obj/x/merge1",
         "is_hda": False, "hda_type": ""},
        {"name": "b", "type": "transform", "path": "/obj/x/b",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [
        {"seg_id": "seg_01_a", "nodes": [
            {"name": "a", "type": "transform", "path": "/obj/x/a",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
        {"seg_id": "seg_02_b", "nodes": [
            {"name": "b", "type": "transform", "path": "/obj/x/b",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
    ]
    narratives = {
        "seg_01_a": {"data": {}, "narrative": "A"},
        "seg_02_b": {"data": {}, "narrative": "B"},
    }
    hwf_orig = {
        "/obj/x/a":      {"hash": "h_a_old", "flags": {}},
        "/obj/x/merge1": {"hash": "h_m",     "flags": {}},
        "/obj/x/b":      {"hash": "h_b",     "flags": {}},
    }
    first_track(
        endnode_path="/obj/x/b",
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=chain,
        enriched=enriched,
        narratives=narratives,
        hashes_with_flags=hwf_orig,
        docs_root=docs,
    )
    seg2_before = (docs / "TEST_HIP" / "OUT_X" / "segments" / "seg_02_b.md").read_text(encoding="utf-8")

    hwf_new = dict(hwf_orig)
    hwf_new["/obj/x/a"] = {"hash": "h_a_NEW", "flags": {}}
    new_extracted = [
        {"name": "a", "type": "transform", "path": "/obj/x/a", "is_hda": False,
         "kind": "data_transform", "flags": {}, "params_non_default": {"new": 42},
         "random_seeds": []},
        {"name": "merge1", "type": "merge", "path": "/obj/x/merge1", "is_hda": False,
         "kind": "data_transform", "flags": {}, "params_non_default": {}, "random_seeds": []},
        {"name": "b", "type": "transform", "path": "/obj/x/b", "is_hda": False,
         "kind": "data_transform", "flags": {}, "params_non_default": {}, "random_seeds": []},
    ]

    result = sync_endnode(
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hashes_with_flags=hwf_new,
        extracted=new_extracted,
        narratives=narratives,
        docs_root=docs,
    )

    assert "seg_01_a" in result["re_rendered"]
    assert "seg_02_b" not in result["re_rendered"]

    seg2_after = (docs / "TEST_HIP" / "OUT_X" / "segments" / "seg_02_b.md").read_text(encoding="utf-8")
    assert seg2_after == seg2_before

    seg1_after = (docs / "TEST_HIP" / "OUT_X" / "segments" / "seg_01_a.md").read_text(encoding="utf-8")
    assert "new" in seg1_after


def test_sync_endnode_ignores_other_endnode_nodes(tmp_path: Path):
    """The defect found in temp/sync_driver.py: when a manifest has
    multiple endnodes, syncing one must NOT mark the other endnode's
    nodes as 'deleted' just because they're not in the current chain.
    """
    docs = tmp_path / "docs"
    first_track(
        endnode_path="/obj/A/OUT_A",
        endnode_name="OUT_A",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=[{"name": "A_node", "type": "transform",
                "path": "/obj/A/A_node", "is_hda": False, "hda_type": ""}],
        enriched=[{
            "seg_id": "seg_01_a_node",
            "nodes": [{"name": "A_node", "type": "transform",
                       "path": "/obj/A/A_node", "is_hda": False,
                       "kind": "data_transform", "flags": {},
                       "params_non_default": {}, "random_seeds": []}],
        }],
        narratives={"seg_01_a_node": {"data": {}, "narrative": "A"}},
        hashes_with_flags={"/obj/A/A_node": {"hash": "h_a", "flags": {}}},
        docs_root=docs,
    )
    first_track(
        endnode_path="/obj/B/OUT_B",
        endnode_name="OUT_B",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=[{"name": "B_node", "type": "transform",
                "path": "/obj/B/B_node", "is_hda": False, "hda_type": ""}],
        enriched=[{
            "seg_id": "seg_01_b_node",
            "nodes": [{"name": "B_node", "type": "transform",
                       "path": "/obj/B/B_node", "is_hda": False,
                       "kind": "data_transform", "flags": {},
                       "params_non_default": {}, "random_seeds": []}],
        }],
        narratives={"seg_01_b_node": {"data": {}, "narrative": "B"}},
        hashes_with_flags={"/obj/B/B_node": {"hash": "h_b", "flags": {}}},
        docs_root=docs,
    )

    result = sync_endnode(
        endnode_name="OUT_B",
        hipname="TEST_HIP",
        hashes_with_flags={"/obj/B/B_node": {"hash": "h_b", "flags": {}}},
        extracted=[{"name": "B_node", "type": "transform",
                    "path": "/obj/B/B_node", "is_hda": False,
                    "kind": "data_transform", "flags": {},
                    "params_non_default": {}, "random_seeds": []}],
        narratives={"seg_01_b_node": {"data": {}, "narrative": "B"}},
        docs_root=docs,
    )
    assert result["diff"]["deleted"] == []
    assert result["diff"]["changed"] == []
    manifest = load_manifest(docs / "TEST_HIP" / "manifest.yaml")
    assert {e["name"] for e in manifest.endnodes} == {"OUT_A", "OUT_B"}
    assert "/obj/A/A_node" in manifest.nodes
    assert "/obj/B/B_node" in manifest.nodes


# ---------- first_track hda_cache_report ----------

def test_first_track_returns_hda_cache_report(tmp_path: Path):
    """When the chain contains a user HDA, first_track must return a
    structured report on whether it's already cached."""
    docs = tmp_path / "docs"
    from ankr.manifest import Manifest, save_manifest
    cached = Manifest(
        hipfile_name="bluei::Cached::1.0",
        hipfile_current="cached.hdalc",
        kind="hda",
        hda_type="bluei::Cached::1.0",
        hda_modification_time=1000.0,
    )
    save_manifest(cached, docs / "custom_hda" / "bluei__Cached__1.0" / "manifest.yaml")

    chain = [
        {"name": "cached_inst", "type": "bluei::Cached::1.0",
         "path": "/obj/X/cached_inst", "is_hda": True,
         "hda_type": "bluei::Cached::1.0"},
        {"name": "missing_inst", "type": "bluei::Missing::1.0",
         "path": "/obj/X/missing_inst", "is_hda": True,
         "hda_type": "bluei::Missing::1.0"},
        {"name": "OUT_X", "type": "null", "path": "/obj/X/OUT_X",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [{
        "seg_id": "seg_01_cached_inst",
        "nodes": [
            {"name": "cached_inst", "type": "bluei::Cached::1.0",
             "path": "/obj/X/cached_inst", "is_hda": True,
             "hda_type": "bluei::Cached::1.0",
             "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []},
            {"name": "missing_inst", "type": "bluei::Missing::1.0",
             "path": "/obj/X/missing_inst", "is_hda": True,
             "hda_type": "bluei::Missing::1.0",
             "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []},
            {"name": "OUT_X", "type": "null", "path": "/obj/X/OUT_X",
             "is_hda": False, "kind": "passthrough", "flags": {},
             "params_non_default": {}, "random_seeds": []},
        ],
    }]
    narratives = {"seg_01_cached_inst": {"data": {}, "narrative": "n"}}
    hwf = {
        "/obj/X/cached_inst":  {"hash": "h_c", "flags": {}},
        "/obj/X/missing_inst": {"hash": "h_m", "flags": {}},
        "/obj/X/OUT_X":        {"hash": "h_o", "flags": {}},
    }

    result = first_track(
        endnode_path="/obj/X/OUT_X",
        endnode_name="OUT_X",
        hipname="HIP_X",
        hip_meta={"hipfile_current": "X.hip", "hipfile_path": "",
                  "houdini_version": "21.0.671"},
        chain=chain,
        enriched=enriched,
        narratives=narratives,
        hashes_with_flags=hwf,
        docs_root=docs,
        hda_mtime_lookup={
            "bluei::Cached::1.0":  1000.0,
            "bluei::Missing::1.0": 9999.0,
        },
    )
    report = result["hda_cache_report"]
    assert "bluei::Cached::1.0"  in report
    assert "bluei::Missing::1.0" in report
    assert report["bluei::Cached::1.0"]["status"]  == "fresh"
    assert report["bluei::Missing::1.0"]["status"] == "missing"


# ---------- Card integration (hip-only subset) ----------

class TestCardIntegrationHip:
    def test_first_track_hip_has_card_step(self, tmp_path):
        docs = tmp_path / "docs"
        result = first_track(
            endnode_path="/obj/KH_terrain/OUT_KH",
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hip_meta=_hip_meta(),
            chain=_simple_chain(),
            enriched=_simple_enriched(),
            narratives=_simple_narratives(),
            hashes_with_flags=_simple_hwf(),
            docs_root=docs,
        )
        assert "card_step" in result
        assert result["card_step"]["status"] == "skipped"  # autouse mock

    def test_sync_no_changes_skips_card(self, tmp_path):
        docs = tmp_path / "docs"
        first_track(
            endnode_path="/obj/KH_terrain/OUT_KH",
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hip_meta=_hip_meta(),
            chain=_simple_chain(),
            enriched=_simple_enriched(),
            narratives=_simple_narratives(),
            hashes_with_flags=_simple_hwf(),
            docs_root=docs,
        )
        result = sync_endnode(
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hashes_with_flags=_simple_hwf(),
            extracted=[n for seg in _simple_enriched() for n in seg["nodes"]],
            narratives=_simple_narratives(),
            docs_root=docs,
        )
        assert result["card_step"]["status"] == "skipped"

    def test_sync_with_changes_calls_card(self, tmp_path):
        docs = tmp_path / "docs"
        first_track(
            endnode_path="/obj/KH_terrain/OUT_KH",
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hip_meta=_hip_meta(),
            chain=_simple_chain(),
            enriched=_simple_enriched(),
            narratives=_simple_narratives(),
            hashes_with_flags=_simple_hwf(),
            docs_root=docs,
        )
        changed_hwf = _simple_hwf()
        changed_hwf["/obj/KH_terrain/kh_terrain"]["hash"] = "h_changed"
        result = sync_endnode(
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hashes_with_flags=changed_hwf,
            extracted=[n for seg in _simple_enriched() for n in seg["nodes"]],
            narratives=_simple_narratives(),
            docs_root=docs,
        )
        assert result["card_step"]["status"] == "skipped"  # mock but key exists
        assert len(result["diff"]["changed"]) > 0

    def test_previous_sync_rotated_on_sync(self, tmp_path, monkeypatch):
        import ankr.drivers._shared_steps as _shared_steps_mod
        import ankr.drivers._hip as _hip_mod
        call_count = [0]
        def _fake_now():
            call_count[0] += 1
            return f"2026-04-09T1{call_count[0]}:00"
        monkeypatch.setattr(_shared_steps_mod, "_now", _fake_now)
        monkeypatch.setattr(_hip_mod, "_now", _fake_now)

        docs = tmp_path / "docs"
        first_track(
            endnode_path="/obj/KH_terrain/OUT_KH",
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hip_meta=_hip_meta(),
            chain=_simple_chain(),
            enriched=_simple_enriched(),
            narratives=_simple_narratives(),
            hashes_with_flags=_simple_hwf(),
            docs_root=docs,
        )
        m1 = load_manifest(docs / "TEST_HIP" / "manifest.yaml")
        first_last_sync = m1.last_sync

        changed_hwf = _simple_hwf()
        changed_hwf["/obj/KH_terrain/OUT_KH"]["hash"] = "h_new"
        sync_endnode(
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hashes_with_flags=changed_hwf,
            extracted=[n for seg in _simple_enriched() for n in seg["nodes"]],
            narratives=_simple_narratives(),
            docs_root=docs,
        )
        m2 = load_manifest(docs / "TEST_HIP" / "manifest.yaml")
        assert m2.previous_sync == first_last_sync
        assert m2.last_sync != first_last_sync

    def test_hip_no_card_yaml(self, tmp_path):
        docs = tmp_path / "docs"
        first_track(
            endnode_path="/obj/KH_terrain/OUT_KH",
            endnode_name="OUT_KH",
            hipname="TEST_HIP",
            hip_meta=_hip_meta(),
            chain=_simple_chain(),
            enriched=_simple_enriched(),
            narratives=_simple_narratives(),
            hashes_with_flags=_simple_hwf(),
            docs_root=docs,
        )
        assert not (docs / "TEST_HIP" / "card.yaml").exists()


# ---------- cross_segment_refs integration ----------

def _chain_with_merge() -> list[dict]:
    return [
        {"name": "terrain_out", "type": "null", "path": "/obj/H/terrain_out",
         "is_hda": False, "hda_type": ""},
        {"name": "merge1", "type": "merge", "path": "/obj/H/merge1",
         "is_hda": False, "hda_type": ""},
        {"name": "road_curve", "type": "curve", "path": "/obj/H/road_curve",
         "is_hda": False, "hda_type": ""},
        {"name": "merge2", "type": "merge", "path": "/obj/H/merge2",
         "is_hda": False, "hda_type": ""},
        {"name": "scatter1", "type": "scatter", "path": "/obj/H/scatter1",
         "is_hda": False, "hda_type": ""},
        {"name": "OUT", "type": "null", "path": "/obj/H/OUT",
         "is_hda": False, "hda_type": ""},
    ]

def _enriched_with_merge() -> list[dict]:
    return [
        {"seg_id": "seg_01_terrain", "nodes": [
            {"name": "terrain_out", "path": "/obj/H/terrain_out",
             "type": "null", "is_hda": False, "kind": "passthrough",
             "flags": {}, "params_non_default": {}, "random_seeds": [],
             "writes": ["height", "N"]},
        ]},
        {"seg_id": "seg_02_road", "nodes": [
            {"name": "road_curve", "path": "/obj/H/road_curve",
             "type": "curve", "is_hda": False, "kind": "data_transform",
             "flags": {}, "params_non_default": {}, "random_seeds": [],
             "writes": ["P"]},
        ]},
        {"seg_id": "seg_03_scatter", "nodes": [
            {"name": "scatter1", "path": "/obj/H/scatter1",
             "type": "scatter", "is_hda": False, "kind": "data_transform",
             "flags": {}, "params_non_default": {}, "random_seeds": [],
             "writes": ["P", "density"]},
            {"name": "OUT", "path": "/obj/H/OUT",
             "type": "null", "is_hda": False, "kind": "passthrough",
             "flags": {}, "params_non_default": {}, "random_seeds": [],
             "writes": []},
        ]},
    ]

def _narratives_with_merge() -> dict:
    return {
        "seg_01_terrain": {"data": {}, "narrative": "terrain"},
        "seg_02_road": {"data": {}, "narrative": "road"},
        "seg_03_scatter": {"data": {}, "narrative": "scatter"},
    }

def _hwf_with_merge() -> dict:
    return {p: {"hash": f"h_{p.split('/')[-1]}", "flags": {}}
            for p in ["/obj/H/terrain_out", "/obj/H/merge1", "/obj/H/road_curve",
                      "/obj/H/merge2", "/obj/H/scatter1", "/obj/H/OUT"]}


def test_first_track_cross_refs_in_skeleton(tmp_path):
    """first_track writes cross_segment_refs to skeleton.md when landmark_inputs provided."""
    result = first_track(
        endnode_path="/obj/H/OUT",
        endnode_name="OUT",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=_chain_with_merge(),
        enriched=_enriched_with_merge(),
        narratives=_narratives_with_merge(),
        hashes_with_flags=_hwf_with_merge(),
        docs_root=tmp_path,
        landmark_inputs={
            "/obj/H/merge2": ["/obj/H/road_curve", "/obj/H/terrain_out"],
        },
    )
    skeleton_path = tmp_path / "TEST_HIP" / "OUT" / "skeleton.md"
    text = skeleton_path.read_text(encoding="utf-8")
    fm_text = text.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert "cross_segment_refs" in fm
    assert len(fm["cross_segment_refs"]) == 1
    assert fm["cross_segment_refs"][0]["from_segment"] == "seg_01_terrain"


# ---------- _patch_skeleton_external_refs ----------

from ankr.drivers._hip import _patch_skeleton_external_refs


def _write_skeleton_with_ext_refs(path, has_ext_refs=True):
    """Write a minimal skeleton.md with or without external refs section."""
    parts = ["---\nendnode: /obj/H/OUT\n---\n", "# skeleton\n\n"]
    if has_ext_refs:
        parts.append("## 외부 참조\n\n")
        parts.append("| 랜드마크 | object_merge 경로 | 소스 경로 | 위치 |\n")
        parts.append("|----------|-------------------|-----------|------|\n")
        parts.append("| M1 | /obj/H/om1 | /obj/OLD/src | seg_01 → seg_02 |\n\n")
    parts.append("## 세그먼트 인덱스\n- [seg_01](segments/seg_01.md)\n")
    path.write_text("".join(parts), encoding="utf-8")


def test_patch_skeleton_replaces_existing_section(tmp_path):
    skel = tmp_path / "skeleton.md"
    _write_skeleton_with_ext_refs(skel, has_ext_refs=True)

    new_refs = [{"landmark_id": "M5", "landmark_path": "/obj/H/om5",
                 "source_path": "/obj/NEW/src", "between": "seg_03 → seg_04"}]
    _patch_skeleton_external_refs(skel, new_refs)

    text = skel.read_text(encoding="utf-8")
    assert "M5" in text
    assert "/obj/NEW/src" in text
    assert "M1" not in text
    assert "## 세그먼트 인덱스" in text


def test_patch_skeleton_inserts_when_no_section(tmp_path):
    skel = tmp_path / "skeleton.md"
    _write_skeleton_with_ext_refs(skel, has_ext_refs=False)

    new_refs = [{"landmark_id": "M2", "landmark_path": "/obj/H/om2",
                 "source_path": "/obj/X/src", "between": ""}]
    _patch_skeleton_external_refs(skel, new_refs)

    text = skel.read_text(encoding="utf-8")
    assert "## 외부 참조" in text
    assert "M2" in text
    ext_pos = text.index("## 외부 참조")
    seg_pos = text.index("## 세그먼트 인덱스")
    assert ext_pos < seg_pos


def test_patch_skeleton_removes_section_when_empty(tmp_path):
    skel = tmp_path / "skeleton.md"
    _write_skeleton_with_ext_refs(skel, has_ext_refs=True)

    _patch_skeleton_external_refs(skel, [])

    text = skel.read_text(encoding="utf-8")
    assert "## 외부 참조" not in text
    assert "## 세그먼트 인덱스" in text


# ---------- sync_endnode with external_refs ----------

def test_sync_endnode_with_external_refs(tmp_path):
    docs = tmp_path / "docs"
    chain = [
        {"name": "om1", "type": "object_merge", "path": "/obj/x/om1",
         "is_hda": False, "hda_type": ""},
        {"name": "a", "type": "transform", "path": "/obj/x/a",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [
        {"seg_id": "seg_01_a", "nodes": [
            {"name": "a", "type": "transform", "path": "/obj/x/a",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
    ]
    hwf = {
        "/obj/x/om1": {"hash": "h_om1", "flags": {}},
        "/obj/x/a":   {"hash": "h_a",   "flags": {}},
    }
    first_track(
        endnode_path="/obj/x/a",
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=chain,
        enriched=enriched,
        narratives={"seg_01_a": {"data": {}, "narrative": "A"}},
        hashes_with_flags=hwf,
        docs_root=docs,
        objpath1_by_landmark={"/obj/x/om1": "/obj/EXT/terrain"},
    )

    skel_text = (docs / "TEST_HIP" / "OUT_X" / "skeleton.md").read_text(encoding="utf-8")
    assert "외부 참조" in skel_text

    hwf_new = dict(hwf)
    hwf_new["/obj/x/a"] = {"hash": "h_a_NEW", "flags": {}}

    result = sync_endnode(
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hashes_with_flags=hwf_new,
        extracted=[
            {"name": "a", "type": "transform", "path": "/obj/x/a",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {"changed": 1}, "random_seeds": []},
        ],
        narratives={"seg_01_a": {"data": {}, "narrative": "A"}},
        docs_root=docs,
        chain=chain,
        objpath1_by_landmark={"/obj/x/om1": "/obj/EXT/new_terrain"},
    )

    assert len(result["external_refs"]) == 1
    assert result["external_refs"][0]["source_path"] == "/obj/EXT/new_terrain"
    skel_after = (docs / "TEST_HIP" / "OUT_X" / "skeleton.md").read_text(encoding="utf-8")
    assert "/obj/EXT/new_terrain" in skel_after


def test_sync_endnode_without_chain_no_external_refs(tmp_path):
    docs = tmp_path / "docs"
    chain = [
        {"name": "a", "type": "transform", "path": "/obj/x/a",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [
        {"seg_id": "seg_01_a", "nodes": [
            {"name": "a", "type": "transform", "path": "/obj/x/a",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
    ]
    hwf = {"/obj/x/a": {"hash": "h_a", "flags": {}}}
    first_track(
        endnode_path="/obj/x/a",
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=chain,
        enriched=enriched,
        narratives={"seg_01_a": {"data": {}, "narrative": "A"}},
        hashes_with_flags=hwf,
        docs_root=docs,
    )
    hwf_new = {"/obj/x/a": {"hash": "h_a_NEW", "flags": {}}}
    result = sync_endnode(
        endnode_name="OUT_X",
        hipname="TEST_HIP",
        hashes_with_flags=hwf_new,
        extracted=[{"name": "a", "type": "transform", "path": "/obj/x/a",
                    "is_hda": False, "kind": "data_transform", "flags": {},
                    "params_non_default": {}, "random_seeds": []}],
        narratives={"seg_01_a": {"data": {}, "narrative": "A"}},
        docs_root=docs,
    )
    assert result["external_refs"] == []


# ---------- first_track with external_refs ----------

def test_first_track_external_refs_in_skeleton(tmp_path):
    chain = [
        {"name": "om1", "type": "object_merge", "path": "/obj/H/om1",
         "is_hda": False, "hda_type": ""},
        {"name": "node1", "type": "transform", "path": "/obj/H/node1",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [
        {"seg_id": "seg_01_node1", "nodes": [
            {"name": "node1", "type": "transform", "path": "/obj/H/node1",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
    ]
    result = first_track(
        endnode_path="/obj/H/node1",
        endnode_name="OUT",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=chain,
        enriched=enriched,
        narratives={},
        hashes_with_flags={
            "/obj/H/om1":   {"hash": "h1", "flags": {}},
            "/obj/H/node1": {"hash": "h2", "flags": {}},
        },
        docs_root=tmp_path,
        objpath1_by_landmark={"/obj/H/om1": "/obj/TERRAIN/OUT"},
    )
    skeleton_text = Path(result["skeleton_path"]).read_text(encoding="utf-8")
    assert "## 외부 참조" in skeleton_text
    assert "/obj/TERRAIN/OUT" in skeleton_text
    fm_text = skeleton_text.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert "external_refs" in fm
    assert len(fm["external_refs"]) == 1


def test_first_track_no_external_refs_without_objpath1(tmp_path):
    chain = [
        {"name": "om1", "type": "object_merge", "path": "/obj/H/om1",
         "is_hda": False, "hda_type": ""},
        {"name": "node1", "type": "transform", "path": "/obj/H/node1",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [
        {"seg_id": "seg_01_node1", "nodes": [
            {"name": "node1", "type": "transform", "path": "/obj/H/node1",
             "is_hda": False, "kind": "data_transform", "flags": {},
             "params_non_default": {}, "random_seeds": []}]},
    ]
    result = first_track(
        endnode_path="/obj/H/node1",
        endnode_name="OUT",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=chain,
        enriched=enriched,
        narratives={},
        hashes_with_flags={
            "/obj/H/om1":   {"hash": "h1", "flags": {}},
            "/obj/H/node1": {"hash": "h2", "flags": {}},
        },
        docs_root=tmp_path,
    )
    skeleton_text = Path(result["skeleton_path"]).read_text(encoding="utf-8")
    assert "## 외부 참조" not in skeleton_text


# ---------- compute_segment_meta ----------

def test_compute_segment_meta_basic():
    seg = {
        "seg_id": "seg_01_test",
        "nodes": [
            {"name": "w1", "type": "attribwrangle", "kind": "wrangle",
             "vex_code": "i@foo = 1;\nf@bar = 2.0;\n"},
            {"name": "blast1", "type": "blast", "kind": "data_transform"},
            {"name": "w2", "type": "attribwrangle", "kind": "wrangle",
             "vex_code": "// comment\nv@P = {0,1,0};\n"},
        ],
    }
    meta = compute_segment_meta(seg)
    assert meta["wrangles"] == 2
    assert meta["vex_lines"] == 3
    assert meta["nodes"] == 3


def test_compute_segment_meta_no_vex():
    seg = {
        "seg_id": "seg_02_test",
        "nodes": [
            {"name": "blast1", "type": "blast", "kind": "data_transform"},
            {"name": "null1", "type": "null", "kind": "passthrough"},
        ],
    }
    meta = compute_segment_meta(seg)
    assert meta["wrangles"] == 0
    assert meta["vex_lines"] == 0
    assert meta["nodes"] == 2


def test_compute_segment_meta_split_calculation():
    """VEX 450줄 → ceil(450/200) = 3파트"""
    big_vex = "\n".join([f"f@attr_{i} = {i}.0;" for i in range(450)])
    seg = {
        "seg_id": "seg_05_heavy",
        "nodes": [
            {"name": "w1", "type": "attribwrangle", "kind": "wrangle",
             "vex_code": big_vex},
        ],
    }
    meta = compute_segment_meta(seg)
    assert meta["vex_lines"] == 450


def test_first_track_generates_dataflow_md(tmp_path: Path):
    """first_track pipeline should write dataflow.md alongside skeleton.md."""
    docs = tmp_path / "docs"
    enriched_with_attribs = [{
        "seg_id": "seg_01_test",
        "nodes": [
            {
                "name": "w1", "type": "attribwrangle",
                "path": "/obj/Test/w1", "is_hda": False,
                "kind": "wrangle", "flags": {},
                "params_non_default": {}, "random_seeds": [],
                "reads": [], "writes": ["foo", "bar"],
                "groups_read": [], "groups_write": [],
                "vex_code": "f@foo = 1.0;\ni@bar = 2;",
            },
        ],
    }]
    narratives = {
        "seg_01_test": {"data": {}, "narrative": "테스트 wrangle"},
    }
    first_track(
        endnode_path="/obj/Test/OUT_Test",
        endnode_name="OUT_Test",
        hipname="TEST_HIP",
        hip_meta=_hip_meta(),
        chain=[
            {"name": "w1", "type": "attribwrangle",
             "path": "/obj/Test/w1", "is_hda": False, "hda_type": ""},
        ],
        enriched=enriched_with_attribs,
        narratives=narratives,
        hashes_with_flags={
            "/obj/Test/w1": {"hash": "h1", "flags": {"bypass": False,
                "lock": False, "template": False, "display": True, "render": True}},
        },
        docs_root=docs,
    )
    dataflow_path = docs / "TEST_HIP" / "OUT_Test" / "dataflow.md"
    assert dataflow_path.exists()
    content = dataflow_path.read_text(encoding="utf-8")
    assert "## 어트리뷰트 흐름" in content
    assert "foo" in content
    assert "bar" in content
