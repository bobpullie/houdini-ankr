"""HDA cache lookup — mtime-based freshness classification for tracked HDAs.

Provides mtime-based cache lookup for tracked HDAs under
docs_root/custom_hda/<safe_id>/. Pure-Python — no Houdini dependency.

NOTE (P1.6 wave 4): the `custom_hda` literal in `hda_manifest_path` is held
over from the legacy layout. The canonical config exposes this as
`docs.hda_subdir` and the driver layer will inject the resolved path so this
module loses the literal. Until drivers are ported, the literal still matches
the config default and behavior is unchanged.
"""
from __future__ import annotations
from pathlib import Path
from typing import Literal, Optional

from .manifest import Manifest, load_manifest


def safe_hda_id(hda_type: str) -> str:
    """`bluei::KJI_SharpPoints_Bevel::1.2` → `bluei__KJI_SharpPoints_Bevel__1.2`.

    Filesystem-safe encoding using a double-underscore in place of `::`.
    Same convention as `ankr.used_by._safe_type_id`.
    """
    return hda_type.replace("::", "__")


def hda_manifest_path(docs_root: Path, hda_type: str) -> Path:
    """Locate the manifest.yaml for a tracked HDA under docs_root."""
    return docs_root / "custom_hda" / safe_hda_id(hda_type) / "manifest.yaml"


CacheStatus = Literal["fresh", "stale", "missing"]


def lookup_hda_cache(
    docs_root: Path,
    hda_type: str,
    current_mtime: float,
    *,
    tolerance: float = 1.0,
) -> tuple[CacheStatus, Optional[Manifest]]:
    """Compare on-disk manifest mtime to current; classify as fresh/stale/missing.

    - "fresh":   manifest exists, kind == "hda", and |stored - current| <= tolerance
    - "stale":   manifest exists, kind == "hda", but mtime differs
    - "missing": no manifest, OR manifest has wrong kind (defensive)
    """
    path = hda_manifest_path(docs_root, hda_type)
    if not path.exists():
        return "missing", None
    m = load_manifest(path)
    if m is None or m.kind != "hda":
        return "missing", None
    if abs(m.hda_modification_time - current_mtime) <= tolerance:
        return "fresh", m
    return "stale", m


def bulk_lookup(
    docs_root: Path,
    hda_types_with_mtime: dict[str, float],
) -> dict[str, tuple[CacheStatus, Optional[Manifest]]]:
    """Vectorized lookup for the post-track HDA cache report."""
    return {
        h: lookup_hda_cache(docs_root, h, m)
        for h, m in hda_types_with_mtime.items()
    }
