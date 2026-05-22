"""Tag vocabulary for controlled HDA tagging (L0/L1 card system).

5-axis tag categories + pending proposals + aliases. Aliases resolve to a
canonical tag during validation; new tag proposals accumulate as
pending_proposals for periodic curation.

Pure-Python — no Houdini runtime dependency. Used by `ankr render-cards`
and Haiku-driven L0 card narrative generation.

NOTE (P1.6 wave 4): the `custom_hda` literal in `_vocab_path` is held over
from the legacy layout. The canonical config exposes this as `docs.hda_subdir`
and the driver layer will inject the resolved path so this module loses the
literal. Until drivers are ported, the literal still matches the config
default and behavior is unchanged.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VOCAB_FILENAME = "_tag_vocabulary.yaml"


@dataclass
class PendingProposal:
    tag: str
    suggested_category: str
    proposed_by: str
    proposed_at: str
    occurrences: int = 1


@dataclass
class PendingCategory:
    name: str
    description: str
    proposed_by: str
    proposed_at: str


@dataclass
class TagVocabulary:
    version: int = 0
    last_updated: str = ""
    categories: dict[str, dict] = field(default_factory=dict)
    pending_proposals: list[dict] = field(default_factory=list)
    pending_categories: list[dict] = field(default_factory=list)


def _vocab_path(docs_root: Path) -> Path:
    return docs_root / "custom_hda" / VOCAB_FILENAME


def load_vocabulary(docs_root: Path) -> TagVocabulary:
    """Load vocabulary from docs_root/custom_hda/_tag_vocabulary.yaml.

    Returns empty vocabulary if file doesn't exist.
    Raises yaml.YAMLError if file is corrupted.
    """
    path = _vocab_path(docs_root)
    if not path.exists():
        return TagVocabulary()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return TagVocabulary()
    return TagVocabulary(
        version=data.get("version", 0),
        last_updated=data.get("last_updated", ""),
        categories=data.get("categories", {}),
        pending_proposals=data.get("pending_proposals", []) or [],
        pending_categories=data.get("pending_categories", []) or [],
    )


def save_vocabulary(docs_root: Path, vocab: TagVocabulary) -> None:
    """Write vocabulary to docs_root/custom_hda/_tag_vocabulary.yaml."""
    data = {
        "version": vocab.version,
        "last_updated": vocab.last_updated,
        "categories": vocab.categories,
        "pending_proposals": vocab.pending_proposals,
        "pending_categories": vocab.pending_categories,
    }
    path = _vocab_path(docs_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _all_canonical_tags(vocab: TagVocabulary) -> set[str]:
    """Collect all canonical tag names across all categories."""
    tags: set[str] = set()
    for cat in vocab.categories.values():
        tags.update(cat.get("tags", {}).keys())
    return tags


def _alias_map(vocab: TagVocabulary) -> dict[str, str]:
    """Build alias -> canonical tag mapping."""
    mapping: dict[str, str] = {}
    for cat in vocab.categories.values():
        for tag_name, tag_info in cat.get("tags", {}).items():
            for alias in tag_info.get("aliases", []):
                mapping[alias] = tag_name
    return mapping


def validate_tags(tags: list[str], vocab: TagVocabulary) -> tuple[list[str], list[str]]:
    """Partition tags into (accepted, rejected) based on vocabulary membership.
    Aliases are resolved to canonical form before validation."""
    canonical = _all_canonical_tags(vocab)
    aliases = _alias_map(vocab)
    accepted: list[str] = []
    rejected: list[str] = []
    for t in tags:
        resolved = aliases.get(t, t)
        if resolved in canonical:
            if resolved not in accepted:
                accepted.append(resolved)
        else:
            rejected.append(t)
    return accepted, rejected


def normalize_alias(tag: str, vocab: TagVocabulary) -> str | None:
    """Resolve an alias to its canonical tag. Returns None if not found."""
    canonical = _all_canonical_tags(vocab)
    if tag in canonical:
        return tag
    aliases = _alias_map(vocab)
    return aliases.get(tag)


def merge_proposals(
    vocab: TagVocabulary,
    proposed: list[dict],
    proposed_by: str,
) -> None:
    """Add new proposals or increment occurrences for existing ones.
    Each proposed dict has: {tag, suggested_category}.
    Mutates vocab.pending_proposals in place."""
    from datetime import datetime
    now = datetime.now().isoformat(timespec="minutes")
    for p in proposed:
        existing = next(
            (pp for pp in vocab.pending_proposals if pp["tag"] == p["tag"]),
            None,
        )
        if existing:
            existing["occurrences"] = existing.get("occurrences", 1) + 1
        else:
            vocab.pending_proposals.append({
                "tag": p["tag"],
                "suggested_category": p.get("suggested_category", ""),
                "proposed_by": proposed_by,
                "proposed_at": now,
                "occurrences": 1,
            })


def increment_counts(vocab: TagVocabulary, accepted_tags: list[str]) -> None:
    """Increment usage count for each accepted tag. Mutates vocab in place."""
    for tag in accepted_tags:
        for cat in vocab.categories.values():
            if tag in cat.get("tags", {}):
                cat["tags"][tag]["count"] = cat["tags"][tag].get("count", 0) + 1
                break


def serialize_vocab_for_haiku(vocab: TagVocabulary) -> dict:
    """Minimal vocabulary representation for Haiku prompt injection.
    Strips counts, dates — only category/tag names/aliases."""
    cats: dict = {}
    for cat_name, cat_info in vocab.categories.items():
        tags: dict = {}
        for tag_name, tag_info in cat_info.get("tags", {}).items():
            tags[tag_name] = {"aliases": tag_info.get("aliases", [])}
        cats[cat_name] = {
            "description": cat_info.get("description", ""),
            "tags": tags,
        }
    return {"categories": cats}
