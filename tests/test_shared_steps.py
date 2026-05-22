"""Tests for drivers/_shared_steps.py — target_kind-dispatched pipeline.

P1.6 Wave 4: legacy parity test (`_steps.py` shim equivalence) dropped; the
canonical package never had a `_steps` shim. Only the target_kind validator
test is retained.
"""
from __future__ import annotations
import pytest

from ankr.drivers._shared_steps import (
    step_prepare, step_render, step_manifest, step_finalize,
)


def _make_minimal_hip_state(tmp_path):
    return {
        "endnode_path": "/obj/test/OUT",
        "endnode_name": "OUT",
        "hipname": "testhip",
        "hip_meta": {"hipfile_current": "test.hip", "hipfile_path": "/tmp/test.hip",
                     "houdini_version": "21.0.0"},
        "chain": [{"path": "/obj/test/OUT/a", "type": "null", "name": "a"}],
        "enriched": [{"seg_id": "seg_01_a",
                      "nodes": [{"path": "/obj/test/OUT/a", "type": "null", "name": "a",
                                 "kind": "null", "random_seeds": [], "flags": {}}]}],
        "narratives": {"seg_01_a": {"narrative": "테스트", "data": {}}},
        "hashes_with_flags": {"/obj/test/OUT/a": {"hash": "h1", "flags": {}}},
        "docs_root": tmp_path / "docs",
        "hda_mtime_lookup": None,
        "landmark_inputs": {},
        "objpath1_by_landmark": {},
    }


def test_shared_steps_rejects_unknown_target_kind(tmp_path):
    """Each step function raises ValueError on unknown target_kind."""
    state = _make_minimal_hip_state(tmp_path)
    for fn in (step_prepare, step_render, step_manifest, step_finalize):
        with pytest.raises(ValueError, match="unknown target_kind"):
            fn(state, target_kind="foo")
