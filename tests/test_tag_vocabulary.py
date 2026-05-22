"""Tests for tag vocabulary management."""
import pytest
import yaml
from pathlib import Path

from ankr.tag_vocabulary import (
    load_vocabulary, save_vocabulary, TagVocabulary,
    validate_tags, normalize_alias, merge_proposals, increment_counts,
    serialize_vocab_for_haiku,
)


def test_load_missing_file_creates_empty(tmp_path: Path):
    """Loading from nonexistent docs_root returns empty vocabulary."""
    vocab = load_vocabulary(tmp_path)
    assert vocab.version == 0
    assert vocab.categories == {}
    assert vocab.pending_proposals == []
    assert vocab.pending_categories == []


def test_load_corrupted_yaml_raises(tmp_path: Path):
    """Loading from corrupted YAML file raises YAMLError."""
    vocab_dir = tmp_path / "custom_hda"
    vocab_dir.mkdir()
    (vocab_dir / "_tag_vocabulary.yaml").write_text("{{{bad yaml", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_vocabulary(tmp_path)


def test_save_load_roundtrip(tmp_path: Path):
    """Save and load vocabulary preserves all fields."""
    vocab = TagVocabulary(
        version=1,
        last_updated="2026-04-09",
        categories={
            "geometry_op": {
                "description": "geo ops",
                "tags": {
                    "bevel": {
                        "added": "2026-04-09",
                        "count": 3,
                        "aliases": ["edge_bevel"],
                    },
                },
            },
        },
        pending_proposals=[
            {
                "tag": "fracture",
                "suggested_category": "geometry_op",
                "proposed_by": "test::HDA::1.0",
                "proposed_at": "2026-04-09",
                "occurrences": 2,
            },
        ],
        pending_categories=[],
    )
    save_vocabulary(tmp_path, vocab)
    loaded = load_vocabulary(tmp_path)
    assert loaded.version == 1
    assert loaded.last_updated == "2026-04-09"
    assert "geometry_op" in loaded.categories
    assert loaded.categories["geometry_op"]["tags"]["bevel"]["count"] == 3
    assert loaded.categories["geometry_op"]["tags"]["bevel"]["aliases"] == ["edge_bevel"]
    assert len(loaded.pending_proposals) == 1
    assert loaded.pending_proposals[0]["occurrences"] == 2


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


def test_validate_tags_all_valid():
    """validate_tags accepts all matching tags."""
    vocab = _seed_vocab()
    accepted, rejected = validate_tags(["bevel", "terrain"], vocab)
    assert accepted == ["bevel", "terrain"]
    assert rejected == []


def test_validate_tags_some_invalid():
    """validate_tags partitions valid and invalid tags."""
    vocab = _seed_vocab()
    accepted, rejected = validate_tags(["bevel", "unknown_tag", "terrain"], vocab)
    assert accepted == ["bevel", "terrain"]
    assert rejected == ["unknown_tag"]


def test_normalize_alias_canonical():
    """normalize_alias returns canonical tag as-is."""
    vocab = _seed_vocab()
    assert normalize_alias("bevel", vocab) == "bevel"


def test_normalize_alias_resolves():
    """normalize_alias resolves aliases to canonical form."""
    vocab = _seed_vocab()
    assert normalize_alias("edge_bevel", vocab) == "bevel"
    assert normalize_alias("polybevel", vocab) == "bevel"


def test_normalize_alias_unknown():
    """normalize_alias returns None for unknown tags."""
    vocab = _seed_vocab()
    assert normalize_alias("nonexistent", vocab) is None


def test_merge_proposals_new():
    """merge_proposals adds new proposals with occurrence count."""
    vocab = _seed_vocab()
    proposed = [{"tag": "fracture", "suggested_category": "geometry_op"}]
    merge_proposals(vocab, proposed, proposed_by="test::HDA::1.0")
    assert len(vocab.pending_proposals) == 1
    assert vocab.pending_proposals[0]["tag"] == "fracture"
    assert vocab.pending_proposals[0]["occurrences"] == 1
    assert vocab.pending_proposals[0]["proposed_by"] == "test::HDA::1.0"


def test_merge_proposals_duplicate_increments():
    """merge_proposals increments occurrence for duplicate proposals."""
    vocab = _seed_vocab()
    vocab.pending_proposals = [
        {"tag": "fracture", "suggested_category": "geometry_op",
         "proposed_by": "first::HDA::1.0", "proposed_at": "2026-04-09", "occurrences": 2},
    ]
    proposed = [{"tag": "fracture", "suggested_category": "geometry_op"}]
    merge_proposals(vocab, proposed, proposed_by="second::HDA::1.0")
    assert len(vocab.pending_proposals) == 1
    assert vocab.pending_proposals[0]["occurrences"] == 3


def test_increment_counts():
    """increment_counts updates usage counts for tags."""
    vocab = _seed_vocab()
    assert vocab.categories["geometry_op"]["tags"]["bevel"]["count"] == 0
    increment_counts(vocab, ["bevel", "terrain"])
    assert vocab.categories["geometry_op"]["tags"]["bevel"]["count"] == 1
    assert vocab.categories["domain"]["tags"]["terrain"]["count"] == 1
    increment_counts(vocab, ["bevel"])
    assert vocab.categories["geometry_op"]["tags"]["bevel"]["count"] == 2


def test_serialize_vocab_for_haiku():
    """serialize_vocab_for_haiku returns minimal schema without counts/dates."""
    vocab = _seed_vocab()
    result = serialize_vocab_for_haiku(vocab)
    assert "categories" in result
    assert "geometry_op" in result["categories"]
    assert "bevel" in result["categories"]["geometry_op"]["tags"]
    assert "aliases" in result["categories"]["geometry_op"]["tags"]["bevel"]
    assert "count" not in result["categories"]["geometry_op"]["tags"]["bevel"]
    assert "added" not in result["categories"]["geometry_op"]["tags"]["bevel"]
