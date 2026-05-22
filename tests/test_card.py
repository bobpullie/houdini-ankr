"""Tests for L0/L1 card system (build, validate, render)."""
from pathlib import Path
import pytest
import yaml

from ankr.card import (
    CardInput, CardOutput, build_card_input, compute_input_hash,
    should_skip_haiku, validate_card_output, render_card_yaml, render_map_yaml,
    write_card_artifacts, update_global_index, finalize_card,
)
from ankr.manifest import Manifest
from ankr.tag_vocabulary import TagVocabulary


def _seed_vocab() -> TagVocabulary:
    """Helper: Create a minimal vocabulary for testing."""
    return TagVocabulary(
        version=1,
        last_updated="2026-04-09",
        categories={
            "geometry_op": {
                "description": "geo ops",
                "tags": {
                    "bevel": {"added": "2026-04-09", "count": 0, "aliases": ["edge_bevel", "polybevel"]},
                    "fuse": {"added": "2026-04-09", "count": 0, "aliases": []},
                },
            },
            "domain": {
                "description": "use domain",
                "tags": {
                    "terrain": {"added": "2026-04-09", "count": 0, "aliases": []},
                },
            },
        },
        pending_proposals=[],
        pending_categories=[],
    )


def _hda_manifest() -> Manifest:
    """Helper: Create a test HDA manifest."""
    return Manifest(
        kind="hda",
        hipfile_name="test",
        hipfile_current="test.hip",
        hda_type="bluei::TestBevel::1.0",
        internal_segments=[
            {"id": "01", "segment": "seg_001", "nodes": ["detect_sharp"]},
            {"id": "02", "segment": "seg_002", "nodes": ["polybevel1"]},
        ],
        nodes={
            "detect_sharp": {"type": "attribwrangle", "hash": "h1", "flags": {}},
            "polybevel1": {"type": "polybevel", "hash": "h2", "flags": {}},
        },
        spare_parameters_schema=[
            {"name": "angle", "type": "float", "default": "45", "label": "Bevel Angle"}
        ],
        nested_hdas=["bluei::OtherHDA::1.0"],
        hda_dependencies=[],
        endnodes=[],
        last_sync="2026-04-09T14:23",
    )


def test_build_card_input_hda():
    """build_card_input assembles CardInput from HDA manifest."""
    manifest = Manifest(
        kind="hda",
        hipfile_name="test",
        hipfile_current="test.hip",
        hda_type="bluei::TestBevel::1.0",
        internal_segments=[{"id": "s1", "segment": "seg_001", "nodes": ["n1", "n2"]}],
        nodes={"n1": {"type": "bevel", "hash": "h1", "flags": {}}, "n2": {"type": "poly", "hash": "h2", "flags": {}}},
        spare_parameters_schema=[{"name": "angle", "type": "float", "default": "0.1"}],
        nested_hdas=["test::Sub::1.0"],
        hda_dependencies=[],
        endnodes=[],
    )
    narratives = {"s1": {"narrative": "Apply bevel\nMore details"}}
    vocab = _seed_vocab()

    input_card = build_card_input(manifest, narratives, vocab)

    assert input_card.kind == "hda"
    assert input_card.id == "bluei::TestBevel::1.0"
    assert len(input_card.segments) == 1
    assert input_card.segments[0]["slug"] == "s1"
    assert input_card.segments[0]["narrative_first_line"] == "Apply bevel"
    assert input_card.segments[0]["key_nodes"] == []
    assert len(input_card.parms) == 1
    assert input_card.parms[0]["name"] == "angle"
    assert input_card.nested_hdas == ["test::Sub::1.0"]
    assert input_card.vocab_version == 1


def test_build_card_input_hip():
    """build_card_input handles hip (SOP-only) manifests."""
    manifest = Manifest(
        kind="hip",
        hipfile_name="TestHip",
        hipfile_current="TestHip_001.hip",
        endnodes=[{"name": "OUT_A", "path": "/obj/geo/OUT_A", "skeleton": "OUT_A/skeleton.md",
                   "node_count": 10, "landmark_count": 2, "segment_count": 3, "last_sync": ""}],
    )
    manifest.nodes = {
        "/obj/geo/a": {"hash": "h1", "type": "null", "referenced_by": ["OUT_A/seg_01"], "flags": {}},
        "/obj/geo/b": {"hash": "h2", "type": "attribwrangle", "referenced_by": ["OUT_A/seg_01"], "flags": {}},
    }
    narratives = {"seg_01": {"narrative": "hip segment\nMore", "data": {}}}
    vocab = _seed_vocab()

    input_card = build_card_input(manifest, narratives, vocab)

    assert input_card.kind == "hip"
    assert input_card.parms == []
    assert input_card.nested_hdas == []


def test_compute_input_hash_deterministic():
    """compute_input_hash produces same hash for same input."""
    card_input = CardInput(
        kind="hda",
        id="test::HDA::1.0",
        segments=[{"slug": "s1", "narrative_first_line": "test", "key_nodes": []}],
        parms=[],
        nested_hdas=[],
        node_histogram={"bevel": 1},
        node_hashes={"n1": "abc123"},
        anomalies=[],
        recent_changes=None,
        vocab_version=1,
    )
    hash1 = compute_input_hash(card_input)
    hash2 = compute_input_hash(card_input)
    assert hash1 == hash2
    assert len(hash1) == 40


def test_compute_input_hash_differs_on_node_change():
    """compute_input_hash changes when node hashes differ."""
    card_input1 = CardInput(
        kind="hda", id="test::HDA::1.0", segments=[], parms=[], nested_hdas=[],
        node_histogram={}, node_hashes={"n1": "hash_v1"}, anomalies=[],
        recent_changes=None, vocab_version=1,
    )
    card_input2 = CardInput(
        kind="hda", id="test::HDA::1.0", segments=[], parms=[], nested_hdas=[],
        node_histogram={}, node_hashes={"n1": "hash_v2"}, anomalies=[],
        recent_changes=None, vocab_version=1,
    )
    assert compute_input_hash(card_input1) != compute_input_hash(card_input2)


def test_compute_input_hash_sensitive_to_vocab_version():
    """compute_input_hash changes when vocab version differs."""
    card_input1 = CardInput(
        kind="hda", id="test::HDA::1.0", segments=[], parms=[], nested_hdas=[],
        node_histogram={}, node_hashes={"n1": "same"}, anomalies=[],
        recent_changes=None, vocab_version=1,
    )
    card_input2 = CardInput(
        kind="hda", id="test::HDA::1.0", segments=[], parms=[], nested_hdas=[],
        node_histogram={}, node_hashes={"n1": "same"}, anomalies=[],
        recent_changes=None, vocab_version=2,
    )
    assert compute_input_hash(card_input1) != compute_input_hash(card_input2)


def test_should_skip_hash_match_and_file_exists(tmp_path: Path):
    """Hash matches stored + card files exist → skip."""
    hda_dir = tmp_path / "custom_hda" / "bluei__TestBevel__1.0"
    hda_dir.mkdir(parents=True)
    (hda_dir / "card.yaml").write_text("dummy", encoding="utf-8")
    (hda_dir / "map.yaml").write_text("dummy", encoding="utf-8")
    (hda_dir / ".card_input_hash").write_text("abc123", encoding="utf-8")
    assert should_skip_haiku(tmp_path, "bluei::TestBevel::1.0", "abc123", kind="hda") is True


def test_should_skip_hash_match_but_file_missing(tmp_path: Path):
    """Hash matches but card.yaml doesn't exist → force render."""
    hda_dir = tmp_path / "custom_hda" / "bluei__TestBevel__1.0"
    hda_dir.mkdir(parents=True)
    (hda_dir / ".card_input_hash").write_text("abc123", encoding="utf-8")
    assert should_skip_haiku(tmp_path, "bluei::TestBevel::1.0", "abc123", kind="hda") is False


def test_should_skip_hash_differs(tmp_path: Path):
    """Hash differs → force render."""
    hda_dir = tmp_path / "custom_hda" / "bluei__TestBevel__1.0"
    hda_dir.mkdir(parents=True)
    (hda_dir / "card.yaml").write_text("dummy", encoding="utf-8")
    (hda_dir / ".card_input_hash").write_text("old_hash", encoding="utf-8")
    assert should_skip_haiku(tmp_path, "bluei::TestBevel::1.0", "abc123", kind="hda") is False


def test_validate_card_output_ok():
    """validate_card_output accepts valid output."""
    vocab = _seed_vocab()
    out = CardOutput(
        purpose="test purpose",
        pipeline=[
            {"stage": "step 1", "segment": "01", "key_nodes": ["a"]},
            {"stage": "step 2", "segment": "02", "key_nodes": ["b"]},
        ],
        parms_roles={"angle": "detection threshold"},
        tags=["bevel"],
        proposed_tags=[],
        nested_purposes={},
    )
    result = validate_card_output(out, segment_count=2, vocab=vocab)
    assert result["ok"] is True
    assert result["accepted_tags"] == ["bevel"]
    assert result["rejected_tags"] == []


def test_validate_card_output_segment_mismatch():
    """validate_card_output rejects mismatched segment count."""
    vocab = _seed_vocab()
    out = CardOutput(
        purpose="test",
        pipeline=[{"stage": "a", "segment": "01", "key_nodes": []}],
        parms_roles={}, tags=[], proposed_tags=[], nested_purposes={},
    )
    result = validate_card_output(out, segment_count=3, vocab=vocab)
    assert result["ok"] is False
    assert "segment count" in result["errors"][0].lower()


def test_validate_card_output_vocab_violation():
    """validate_card_output separates rejected tags."""
    vocab = _seed_vocab()
    out = CardOutput(
        purpose="test",
        pipeline=[{"stage": "a", "segment": "01", "key_nodes": []}],
        parms_roles={}, tags=["bevel", "nonexistent"], proposed_tags=[], nested_purposes={},
    )
    result = validate_card_output(out, segment_count=1, vocab=vocab)
    assert result["ok"] is True
    assert result["accepted_tags"] == ["bevel"]
    assert result["rejected_tags"] == ["nonexistent"]


def test_render_card_yaml_hda():
    m = _hda_manifest()
    out = CardOutput(
        purpose="날카로운 포인트 베벨",
        pipeline=[
            {"stage": "sharp point 감지", "segment": "01", "key_nodes": ["detect_sharp"]},
            {"stage": "베벨 적용", "segment": "02", "key_nodes": ["polybevel1"]},
        ],
        parms_roles={"angle": "감지 각도 임계값"},
        tags=["bevel"],
        proposed_tags=[],
        nested_purposes={"bluei::OtherHDA::1.0": "other purpose"},
    )
    result = render_card_yaml(out, m)
    parsed = yaml.safe_load(result)
    assert parsed["type"] == "bluei::TestBevel::1.0"
    assert parsed["purpose"] == "날카로운 포인트 베벨"
    assert len(parsed["parms"]) == 1
    assert parsed["parms"][0]["role"] == "감지 각도 임계값"
    assert parsed["tags"] == ["bevel"]
    assert "io" in parsed


def test_render_card_yaml_hip_raises():
    m = Manifest(hipfile_name="TestHip", hipfile_current="test.hip", kind="hip")
    out = CardOutput(purpose="x", pipeline=[], parms_roles={}, tags=[], proposed_tags=[], nested_purposes={})
    with pytest.raises(ValueError, match="L0.*HDA"):
        render_card_yaml(out, m)


def test_render_map_yaml_hda_no_recent():
    m = _hda_manifest()
    m.last_sync = "2026-04-09T14:23"
    out = CardOutput(
        purpose="test",
        pipeline=[
            {"stage": "감지", "segment": "01", "key_nodes": ["detect_sharp"]},
            {"stage": "베벨", "segment": "02", "key_nodes": ["polybevel1"]},
        ],
        parms_roles={},
        tags=["bevel"],
        proposed_tags=[],
        nested_purposes={"bluei::OtherHDA::1.0": "other purpose"},
    )
    result = render_map_yaml(out, m, recent_changes=None)
    parsed = yaml.safe_load(result)
    assert parsed["kind"] == "hda"
    assert parsed["id"] == "bluei::TestBevel::1.0"
    assert len(parsed["pipeline"]) == 2
    assert "node_histogram" in parsed
    assert parsed["nested_hdas"][0]["type"] == "bluei::OtherHDA::1.0"
    assert "recent_changes" not in parsed
    assert "anchors" in parsed


def test_render_map_yaml_with_recent_changes():
    m = _hda_manifest()
    m.last_sync = "2026-04-09T14:23"
    m.previous_sync = "2026-04-09T11:00"
    out = CardOutput(
        purpose="test",
        pipeline=[
            {"stage": "감지", "segment": "01", "key_nodes": ["detect_sharp"]},
            {"stage": "베벨", "segment": "02", "key_nodes": ["polybevel1"]},
        ],
        parms_roles={}, tags=[], proposed_tags=[], nested_purposes={},
    )
    recent = {
        "summary": "1 segment changed",
        "changed_segments": [{"segment": "02", "nodes_changed": 1}],
        "added_nodes": [],
        "deleted_nodes": [],
    }
    result = render_map_yaml(out, m, recent_changes=recent)
    parsed = yaml.safe_load(result)
    assert "recent_changes" in parsed
    assert parsed["recent_changes"]["summary"] == "1 segment changed"
    assert parsed["recent_changes"]["previous_sync"] == "2026-04-09T11:00"


def test_write_card_artifacts_hda(tmp_path: Path):
    target = tmp_path / "custom_hda" / "bluei__Test__1.0"
    target.mkdir(parents=True)
    write_card_artifacts(
        target_dir=target,
        kind="hda",
        card_yaml_str="type: test\n",
        map_yaml_str="kind: hda\n",
        input_hash="abc123",
    )
    assert (target / "card.yaml").read_text(encoding="utf-8") == "type: test\n"
    assert (target / "map.yaml").read_text(encoding="utf-8") == "kind: hda\n"
    assert (target / ".card_input_hash").read_text(encoding="utf-8") == "abc123"


def test_write_card_artifacts_hip(tmp_path: Path):
    target = tmp_path / "TestHip"
    target.mkdir(parents=True)
    write_card_artifacts(
        target_dir=target,
        kind="hip",
        card_yaml_str=None,
        map_yaml_str="kind: hip\n",
        input_hash="def456",
    )
    assert not (target / "card.yaml").exists()
    assert (target / "map.yaml").exists()
    assert (target / ".card_input_hash").read_text(encoding="utf-8") == "def456"


def test_update_global_index_first_entry(tmp_path: Path):
    (tmp_path / "custom_hda").mkdir(parents=True)
    summary = {"type": "bluei::A::1.0", "purpose": "test", "tags": ["bevel"], "last_sync": "2026-04-09"}
    update_global_index(tmp_path, "bluei::A::1.0", summary)
    idx = yaml.safe_load((tmp_path / "custom_hda" / "index.yaml").read_text(encoding="utf-8"))
    assert len(idx["hdas"]) == 1
    assert idx["hdas"][0]["type"] == "bluei::A::1.0"


def test_update_global_index_upsert(tmp_path: Path):
    (tmp_path / "custom_hda").mkdir(parents=True)
    summary1 = {"type": "bluei::A::1.0", "purpose": "old", "tags": [], "last_sync": "2026-04-08"}
    update_global_index(tmp_path, "bluei::A::1.0", summary1)
    summary2 = {"type": "bluei::A::1.0", "purpose": "new", "tags": ["bevel"], "last_sync": "2026-04-09"}
    update_global_index(tmp_path, "bluei::A::1.0", summary2)
    idx = yaml.safe_load((tmp_path / "custom_hda" / "index.yaml").read_text(encoding="utf-8"))
    assert len(idx["hdas"]) == 1
    assert idx["hdas"][0]["purpose"] == "new"


def test_finalize_card_success(tmp_path: Path):
    """finalize_card writes card.yaml + map.yaml on valid output."""
    m = _hda_manifest()
    m.last_sync = "2026-04-09T14:00"
    vocab = _seed_vocab()
    ci = build_card_input(m, {}, vocab)
    ci.input_hash = compute_input_hash(ci)
    target_dir = tmp_path / "custom_hda" / "bluei__TestBevel__1.0"
    target_dir.mkdir(parents=True)

    card_output_json = {
        "purpose": "test purpose",
        "pipeline": [
            {"stage": "step1", "segment": "01", "key_nodes": ["a"]},
            {"stage": "step2", "segment": "02", "key_nodes": ["b"]},
        ],
        "parms_roles": {"angle": "threshold"},
        "tags": ["bevel"],
        "proposed_tags": [],
        "nested_purposes": {},
    }

    result = finalize_card(
        card_output_json=card_output_json,
        card_input=ci,
        manifest=m,
        vocab=vocab,
        target_dir=target_dir,
        temp=tmp_path / "temp",
    )
    assert result["status"] == "success"
    assert (target_dir / "card.yaml").exists()
    assert (target_dir / "map.yaml").exists()


def test_finalize_card_validation_failure(tmp_path: Path):
    """finalize_card returns failed on invalid output (missing purpose)."""
    m = _hda_manifest()
    m.last_sync = "2026-04-09T14:00"
    vocab = _seed_vocab()
    ci = build_card_input(m, {}, vocab)
    ci.input_hash = compute_input_hash(ci)
    target_dir = tmp_path / "custom_hda" / "bluei__TestBevel__1.0"
    target_dir.mkdir(parents=True)

    bad_output_json = {
        "purpose": "",
        "pipeline": [],
        "parms_roles": {},
        "tags": [],
        "proposed_tags": [],
        "nested_purposes": {},
    }

    result = finalize_card(
        card_output_json=bad_output_json,
        card_input=ci,
        manifest=m,
        vocab=vocab,
        target_dir=target_dir,
        temp=tmp_path / "temp",
    )
    assert result["status"] == "failed"
    assert len(result["errors"]) > 0
