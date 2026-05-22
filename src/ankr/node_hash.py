"""Node hash computation. Canonical serialize → sha256.

Hash inputs (per ANKR spec §5.2):
- Static params         → evaluated value
- Dynamic expressions   → expression string (`{"_expression": "<str>"}`)
- VEX code              → full body
- Flags                 → bypass / lock / template / display / render
- Seed values           → broken out for diff highlighting

Excluded: position, color, comments (visual / non-semantic).
"""

from __future__ import annotations

import hashlib
import json


def canonical_serialize(node_info: dict) -> str:
    """Canonical JSON serialization with sorted keys + stable separators."""
    return json.dumps(node_info, sort_keys=True, separators=(",", ":"), default=str)


def compute_node_hash(node_info: dict) -> str:
    """Compute sha256 hash of a node info dict."""
    canonical = canonical_serialize(node_info)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
