"""Tests for extract_and_dump in hou_runtime.py.

Since hou_runtime functions require the Houdini `hou` module (only available
inside a Houdini session), we mock `hou` and the three pipeline functions.
"""
import json
import os
import sys
import tempfile
import types
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixture: fake `hou` module injected into sys.modules before import
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_hou(monkeypatch):
    """Inject a minimal fake ``hou`` module so hou_runtime can be imported."""
    fake_hou = types.ModuleType("hou")

    # hou.hipFile
    hip_file = types.SimpleNamespace(
        name=lambda: "TestHip_v01.hiplc",
        path=lambda: "D:/PROJ/TestHip_v01.hiplc",
    )
    fake_hou.hipFile = hip_file
    fake_hou.applicationVersionString = lambda: "21.0.671"

    monkeypatch.setitem(sys.modules, "hou", fake_hou)
    yield fake_hou


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

CHAIN = [
    {"name": "box1", "type": "box", "path": "/obj/geo/box1", "is_hda": False, "hda_type": ""},
    {"name": "OUT", "type": "null", "path": "/obj/geo/OUT", "is_hda": False, "hda_type": ""},
]

SEGMENTS = [
    {"name": "box1", "type": "box", "path": "/obj/geo/box1", "kind": "data_transform", "params_non_default": {}},
    {"name": "OUT", "type": "null", "path": "/obj/geo/OUT", "kind": "passthrough", "params_non_default": {}},
]

HASHES = {
    "/obj/geo/box1": {"hash": "aaa", "flags": {"bypass": False}},
    "/obj/geo/OUT": {"hash": "bbb", "flags": {"bypass": False}},
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractAndDump:
    def test_extract_and_dump_writes_four_files(self):
        """chain.json, segments_enriched.json, hashes_with_flags.json, scene_meta.json are created."""
        from ankr.hou_runtime import extract_and_dump

        with tempfile.TemporaryDirectory() as td:
            with mock.patch("ankr.hou_runtime.list_endnode_chain", return_value=CHAIN), \
                 mock.patch("ankr.hou_runtime.extract_segment_nodes", return_value=SEGMENTS), \
                 mock.patch("ankr.hou_runtime.compute_hashes_and_flags_for_paths", return_value=HASHES):
                result = extract_and_dump("/obj/geo/OUT", td)

            # Four files must exist
            expected_files = ["chain.json", "segments_enriched.json", "hashes_with_flags.json", "scene_meta.json"]
            for fname in expected_files:
                fpath = os.path.join(td, fname)
                assert os.path.isfile(fpath), f"{fname} was not written"

            # Verify chain.json content
            with open(os.path.join(td, "chain.json"), "r", encoding="utf-8") as f:
                chain_data = json.load(f)
            assert chain_data == CHAIN

            # Verify segments_enriched.json content (segmented format)
            with open(os.path.join(td, "segments_enriched.json"), "r", encoding="utf-8") as f:
                seg_data = json.load(f)
            assert len(seg_data) == 1  # single segment (no landmarks)
            assert seg_data[0]["seg_id"] == "seg_01_box1"
            assert seg_data[0]["endnode"] == "/obj/geo/OUT"
            assert len(seg_data[0]["nodes"]) == 2

            # Verify hashes_with_flags.json content
            with open(os.path.join(td, "hashes_with_flags.json"), "r", encoding="utf-8") as f:
                hash_data = json.load(f)
            assert hash_data == HASHES

            # Verify scene_meta.json content
            with open(os.path.join(td, "scene_meta.json"), "r", encoding="utf-8") as f:
                meta = json.load(f)
            assert meta["hipname"] == "TestHip"
            assert meta["hipfile_current"] == "TestHip_v01.hiplc"
            assert meta["hipfile_path"] == "D:/PROJ/TestHip_v01.hiplc"
            assert meta["houdini_version"] == "21.0.671"

    def test_extract_and_dump_returns_summary(self):
        """Return dict has summary fields and does NOT contain bulk data."""
        from ankr.hou_runtime import extract_and_dump

        with tempfile.TemporaryDirectory() as td:
            with mock.patch("ankr.hou_runtime.list_endnode_chain", return_value=CHAIN), \
                 mock.patch("ankr.hou_runtime.extract_segment_nodes", return_value=SEGMENTS), \
                 mock.patch("ankr.hou_runtime.compute_hashes_and_flags_for_paths", return_value=HASHES):
                result = extract_and_dump("/obj/geo/OUT", td)

        assert result["status"] == "ok"
        assert result["node_count"] == 2
        assert result["segment_count"] == 1  # 1 segment (no landmarks)
        assert result["endnode_name"] == "OUT"
        assert result["hipname"] == "TestHip"

        # Must NOT contain bulk data keys
        for key in ("chain", "segments", "enriched", "hashes", "hashes_with_flags"):
            assert key not in result, f"summary must not contain bulk key '{key}'"

    def test_extract_and_dump_hipname_uses_hip_to_folder(self):
        """hipname is derived from hip_to_folder, e.g. 'TestHip_v01.hiplc' -> 'TestHip'."""
        from ankr.hou_runtime import extract_and_dump

        with tempfile.TemporaryDirectory() as td:
            with mock.patch("ankr.hou_runtime.list_endnode_chain", return_value=CHAIN), \
                 mock.patch("ankr.hou_runtime.extract_segment_nodes", return_value=SEGMENTS), \
                 mock.patch("ankr.hou_runtime.compute_hashes_and_flags_for_paths", return_value=HASHES):
                result = extract_and_dump("/obj/geo/OUT", td)

            # hip_to_folder("TestHip_v01.hiplc") should produce "TestHip"
            assert result["hipname"] == "TestHip"

            # Also verify scene_meta was written with the correct hipname
            with open(os.path.join(td, "scene_meta.json"), "r", encoding="utf-8") as f:
                meta = json.load(f)
            assert meta["hipname"] == "TestHip"

    def test_extract_and_dump_writes_landmark_inputs(self):
        """landmark_inputs.json is created with correct content for landmark nodes."""
        from ankr.hou_runtime import extract_and_dump

        chain_with_merge = [
            {"name": "box1", "type": "box", "path": "/obj/geo/box1", "is_hda": False, "hda_type": ""},
            {"name": "merge1", "type": "merge", "path": "/obj/geo/merge1", "is_hda": False, "hda_type": ""},
            {"name": "OUT", "type": "null", "path": "/obj/geo/OUT", "is_hda": False, "hda_type": ""},
        ]
        segments_3 = SEGMENTS + [
            {"name": "merge1", "type": "merge", "path": "/obj/geo/merge1", "kind": "branch", "params_non_default": {}},
        ]
        hashes_3 = dict(HASHES)
        hashes_3["/obj/geo/merge1"] = {"hash": "ccc", "flags": {"bypass": False}}

        expected_landmark_inputs = {
            "/obj/geo/merge1": ["/obj/geo/box1", "/obj/geo/box2"],
        }

        with tempfile.TemporaryDirectory() as td:
            with mock.patch("ankr.hou_runtime.list_endnode_chain", return_value=chain_with_merge), \
                 mock.patch("ankr.hou_runtime.extract_segment_nodes", return_value=segments_3), \
                 mock.patch("ankr.hou_runtime.compute_hashes_and_flags_for_paths", return_value=hashes_3), \
                 mock.patch("ankr.hou_runtime.extract_landmark_inputs", return_value=expected_landmark_inputs):
                result = extract_and_dump("/obj/geo/OUT", td)

            # landmark_inputs.json must exist
            li_path = os.path.join(td, "landmark_inputs.json")
            assert os.path.isfile(li_path), "landmark_inputs.json was not written"

            with open(li_path, "r", encoding="utf-8") as f:
                li_data = json.load(f)
            assert li_data == expected_landmark_inputs

            # Summary should include landmark_input_count
            assert result["landmark_input_count"] == 1


class TestExtractLandmarkInputs:
    def test_extract_landmark_inputs_basic(self, _fake_hou):
        """Merge with 2 inputs returns both paths."""
        inp0 = types.SimpleNamespace(path=lambda: "/obj/geo/box1")
        inp1 = types.SimpleNamespace(path=lambda: "/obj/geo/box2")
        merge_node = types.SimpleNamespace(inputs=lambda: (inp0, inp1))

        _fake_hou.node = lambda p: merge_node if p == "/obj/geo/merge1" else None

        from ankr.hou_runtime import extract_landmark_inputs

        result = extract_landmark_inputs(["/obj/geo/merge1"])
        assert result == {"/obj/geo/merge1": ["/obj/geo/box1", "/obj/geo/box2"]}

    def test_extract_landmark_inputs_with_none(self, _fake_hou):
        """Disconnected slot appears as None."""
        inp0 = types.SimpleNamespace(path=lambda: "/obj/geo/box1")
        merge_node = types.SimpleNamespace(inputs=lambda: (inp0, None))

        _fake_hou.node = lambda p: merge_node if p == "/obj/geo/merge1" else None

        from ankr.hou_runtime import extract_landmark_inputs

        result = extract_landmark_inputs(["/obj/geo/merge1"])
        assert result == {"/obj/geo/merge1": ["/obj/geo/box1", None]}

    def test_extract_landmark_inputs_missing_node(self, _fake_hou):
        """Non-existent node path returns empty dict."""
        _fake_hou.node = lambda p: None

        from ankr.hou_runtime import extract_landmark_inputs

        result = extract_landmark_inputs(["/obj/geo/nonexistent"])
        assert result == {}
