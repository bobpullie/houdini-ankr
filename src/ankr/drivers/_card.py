"""Card step (L0/L1) — prepare card_input.json for agent-driven Haiku call.

Subcommand context: `ankr track` (and `ankr sync` / `ankr track-hda` / `ankr
sync-hda`). The card step is shared by every driver that emits a manifest.

NOTE (P1.6 wave 4): the `custom_hda` literal for hda target_kind is retained
1:1 from legacy. Removal is bundled with the HDA driver port (T4) — at that
point all 6 hda-scoped literals across card / dataflow / hda_cache /
tag_vocabulary / used_by are excised together as drivers inject
`paths.hda_docs_dir(cfg)`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..card import (
    build_card_input, compute_input_hash, should_skip_haiku,
    serialize_card_input, update_global_index,
)
from ..tag_vocabulary import load_vocabulary, save_vocabulary, merge_proposals, increment_counts


def prepare_card_step(
    *,
    docs_root: Path,
    target_kind: str,
    target_id: str,
    manifest: "Manifest",
    narratives: dict,
    diff_result: dict | None,
    temp: Path,
    prefix: str,
) -> dict:
    """Prepare card_input.json for agent-driven Haiku call. Spec §4.3.

    Returns:
        {"status": "skipped", "reason": ...} if input_hash unchanged.
        {"status": "pending_haiku", "card_input_path": ..., "target_dir": ..., "input_hash": ...}
            when Haiku call is needed (agent handles Phase 2).
    """
    vocab = load_vocabulary(docs_root)
    recent_changes = None
    if diff_result is not None:
        changed = diff_result.get("changed", [])
        added = diff_result.get("added", [])
        deleted = diff_result.get("deleted", [])
        if changed or added or deleted:
            recent_changes = {
                "summary": f"{len(changed)} changed, {len(added)} added, {len(deleted)} deleted",
                "changed_segments": [],
                "added_nodes": added,
                "deleted_nodes": deleted,
            }

    card_input = build_card_input(manifest, narratives, vocab, recent_changes=recent_changes)
    card_input.input_hash = compute_input_hash(card_input)

    if should_skip_haiku(docs_root, target_id, card_input.input_hash, kind=target_kind):
        return {"status": "skipped", "reason": "input_hash_unchanged"}

    if target_kind == "hda":
        safe = target_id.replace("::", "__")
        target_dir = docs_root / "custom_hda" / safe
    else:
        target_dir = docs_root / target_id

    temp_dir = Path(temp) / f"{prefix}_card"
    temp_dir.mkdir(parents=True, exist_ok=True)

    input_data = serialize_card_input(card_input, vocab)
    card_input_path = temp_dir / "card_input.json"
    card_input_path.write_text(
        json.dumps(input_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return {
        "status": "pending_haiku",
        "card_input_path": str(card_input_path),
        "target_dir": str(target_dir),
        "input_hash": card_input.input_hash,
    }
