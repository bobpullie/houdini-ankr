"""ANKR topology — KB walker + invariants I1~I10.

This is the "checker" half of ANKR. It reads a knowledge base produced by the
(yet-to-be-ported) tracker, scans its structure, and reports invariant
violations. No mutation. No Houdini dependency. Pure stdlib + PyYAML.

Layer model (matches legacy ANKR convention):

    <docs_root>/                                  # KB root
    ├── <hipname>/                                # hip endnode group
    │   ├── manifest.yaml                         # L3 (group-level)
    │   └── <endnode_name>/                       # one endnode unit
    │       ├── skeleton.md                       # L1 (required)
    │       ├── dataflow.md                       # L1.5 (optional)
    │       ├── card.md                           # L0 (optional)
    │       └── segments/
    │           └── seg_<N>_<slug>.md             # L2
    │
    └── <hda_subdir>/                             # default "custom_hda/"
        └── <safe_hda_id>/                        # one HDA unit
            ├── manifest.yaml                     # L3 (per-HDA)
            ├── skeleton.md                       # L1 (required)
            ├── dataflow.md, card.md, used_by.md  # L1.5/L0/backlinks (optional)
            └── segments/
                └── seg_<N>_<slug>.md             # L2

If `cfg.docs.hip_subdir` is non-empty, hip groups live under that subdir
(`<docs_root>/<hip_subdir>/<hipname>/...`). Default is empty (legacy).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .config import AnkrConfig


# ---------------------------------------------------------------------------
# File-size caps (per Phase 1 I5)
# ---------------------------------------------------------------------------

MAX_LINES: dict[str, int] = {
    "card": 200,
    "skeleton": 600,
    "dataflow": 400,
    "segment": 800,
    "used_by": 500,
}

MANIFEST_WARN_LINES = 50_000

SEGMENT_FILENAME_RE = re.compile(r"^seg_\d+.*\.md$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    invariant_id: str  # "I1" .. "I10"
    severity: Severity
    path: Path
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "severity": self.severity.value,
            "path": str(self.path),
            "message": self.message,
        }


@dataclass
class KbUnit:
    """One tracked unit on disk — either a hip endnode dir or an HDA dir."""

    kind: str  # "hip" | "hda"
    root: Path
    skeleton: Path | None
    manifest: Path | None
    segments: list[Path] = field(default_factory=list)
    dataflow: Path | None = None
    card: Path | None = None
    used_by: Path | None = None


@dataclass
class ScanResult:
    """Outcome of walking a KB on disk."""

    docs_root: Path
    units: list[KbUnit] = field(default_factory=list)
    unscoped_skeletons: list[Path] = field(default_factory=list)  # I9 candidates
    orphan_segments: list[Path] = field(default_factory=list)  # I2 candidates


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Return the parsed frontmatter dict, or {} if absent / malformed.

    Designed to never raise on bad YAML — invariants report violations, not
    crashes. The body of the markdown is discarded.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except (OSError, UnicodeDecodeError):
        return 0


# ---------------------------------------------------------------------------
# KB scanner
# ---------------------------------------------------------------------------


def scan_kb(cfg: AnkrConfig) -> ScanResult:
    """Walk the configured docs_root and return a structural inventory."""
    docs = paths.docs_root(cfg)
    result = ScanResult(docs_root=docs)
    if not docs.exists():
        return result

    hda_dir = paths.hda_docs_dir(cfg)

    # --- HDAs ---
    if hda_dir.exists():
        for hda_root in sorted(p for p in hda_dir.iterdir() if p.is_dir()):
            result.units.append(_build_unit(hda_root, kind="hda"))

    # --- hip endnodes ---
    # Endnode dir = any dir containing a skeleton.md, excluding the HDA tree.
    for skel in sorted(docs.rglob("skeleton.md")):
        try:
            skel.resolve().relative_to(hda_dir.resolve())
            continue  # under HDA tree — already collected
        except (ValueError, OSError):
            pass
        endnode_root = skel.parent
        if not any(u.root == endnode_root for u in result.units):
            result.units.append(_build_unit(endnode_root, kind="hip"))

    # --- orphan segments (no sibling skeleton) ---
    for seg in sorted(docs.rglob("seg_*.md")):
        if seg.parent.name != "segments":
            continue
        parent = seg.parent.parent
        if not (parent / "skeleton.md").exists():
            result.orphan_segments.append(seg)

    return result


def _build_unit(root: Path, *, kind: str) -> KbUnit:
    skel = root / "skeleton.md"
    manifest = root / "manifest.yaml"
    seg_dir = root / "segments"
    segments = (
        sorted(p for p in seg_dir.iterdir() if SEGMENT_FILENAME_RE.match(p.name))
        if seg_dir.is_dir()
        else []
    )
    return KbUnit(
        kind=kind,
        root=root,
        skeleton=skel if skel.exists() else None,
        manifest=manifest if manifest.exists() else None,
        segments=segments,
        dataflow=(root / "dataflow.md") if (root / "dataflow.md").exists() else None,
        card=(root / "card.md") if (root / "card.md").exists() else None,
        used_by=(root / "used_by.md") if (root / "used_by.md").exists() else None,
    )


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def check_i1_skeleton_present(scan: ScanResult) -> list[Violation]:
    """I1 — every tracked unit has exactly one skeleton.md."""
    out: list[Violation] = []
    for u in scan.units:
        if u.skeleton is None:
            out.append(Violation("I1", Severity.CRITICAL, u.root, "missing skeleton.md"))
    return out


def check_i2_no_orphan_segments(scan: ScanResult) -> list[Violation]:
    """I2 — no segment file lives without a sibling skeleton.md."""
    return [
        Violation("I2", Severity.CRITICAL, seg, "orphan segment: no sibling skeleton.md in parent dir")
        for seg in scan.orphan_segments
    ]


def check_i3_manifest_uniqueness(scan: ScanResult) -> list[Violation]:
    """I3 — manifest presence/uniqueness per unit.

    Uniqueness ("at most one manifest.yaml") is enforced trivially by the
    filesystem: a directory cannot hold two files with the same name. What
    this checker *actually* asserts is the HDA-only presence requirement:
    every HDA unit must carry a `manifest.yaml`. Hip units are allowed to
    omit it (manifest may live at hipname level instead).
    """
    out: list[Violation] = []
    for u in scan.units:
        if u.kind == "hda" and u.manifest is None:
            out.append(Violation("I3", Severity.CRITICAL, u.root, "HDA unit missing manifest.yaml"))
    return out


def check_i8_required_frontmatter(scan: ScanResult) -> list[Violation]:
    """I8 — required frontmatter keys present on skeleton.md and segment .md files."""
    out: list[Violation] = []
    skeleton_required = {"endnode", "last_sync"}
    segment_required = {"segment_id"}
    for u in scan.units:
        if u.skeleton is not None:
            fm = read_frontmatter(u.skeleton)
            missing = skeleton_required - fm.keys()
            if missing:
                out.append(
                    Violation(
                        "I8",
                        Severity.CRITICAL,
                        u.skeleton,
                        f"skeleton.md missing frontmatter keys: {sorted(missing)}",
                    )
                )
        for seg in u.segments:
            fm = read_frontmatter(seg)
            missing = segment_required - fm.keys()
            if missing:
                out.append(
                    Violation(
                        "I8",
                        Severity.CRITICAL,
                        seg,
                        f"segment missing frontmatter keys: {sorted(missing)}",
                    )
                )
    return out


def check_i9_path_layout(cfg: AnkrConfig, scan: ScanResult) -> list[Violation]:
    """I9 — units live in the configured location (hip below docs_root, HDA below hda_subdir)."""
    out: list[Violation] = []
    docs = paths.docs_root(cfg)
    hda_dir = paths.hda_docs_dir(cfg)
    for u in scan.units:
        try:
            rel = u.root.resolve().relative_to(docs.resolve())
        except ValueError:
            out.append(Violation("I9", Severity.CRITICAL, u.root, "unit outside docs_root"))
            continue
        parts = rel.parts
        if u.kind == "hda":
            # Expect first part to be hda_subdir name.
            if not parts or parts[0] != cfg.docs.hda_subdir:
                out.append(
                    Violation(
                        "I9",
                        Severity.CRITICAL,
                        u.root,
                        f"HDA unit not under '{cfg.docs.hda_subdir}/'",
                    )
                )
            elif len(parts) != 2:
                out.append(
                    Violation(
                        "I9",
                        Severity.CRITICAL,
                        u.root,
                        f"HDA unit at unexpected depth (expected <hda_subdir>/<safe_id>/, got {rel})",
                    )
                )
        else:  # hip
            # Hip endnode dir. Two configurations are valid:
            #   (a) hip_subdir set → path must be `<hip_subdir>/<hipname>/<endnode>/` (depth 3).
            #   (b) hip_subdir == "" → path must be `<hipname>/<endnode>/` (depth 2),
            #       and the first part must NOT be hda_subdir (already filtered by the
            #       scanner, but re-checked here for defense-in-depth).
            if cfg.docs.hip_subdir:
                if not parts or parts[0] != cfg.docs.hip_subdir:
                    out.append(
                        Violation(
                            "I9",
                            Severity.CRITICAL,
                            u.root,
                            f"hip endnode not under '{cfg.docs.hip_subdir}/'",
                        )
                    )
                elif len(parts) != 3:
                    out.append(
                        Violation(
                            "I9",
                            Severity.CRITICAL,
                            u.root,
                            f"hip endnode at unexpected depth (expected "
                            f"<hip_subdir>/<hipname>/<endnode>/, got {rel})",
                        )
                    )
            else:
                if parts and parts[0] == cfg.docs.hda_subdir:
                    out.append(
                        Violation(
                            "I9",
                            Severity.CRITICAL,
                            u.root,
                            f"hip endnode wrongly nested under hda_subdir '{cfg.docs.hda_subdir}/'",
                        )
                    )
                elif len(parts) != 2:
                    out.append(
                        Violation(
                            "I9",
                            Severity.CRITICAL,
                            u.root,
                            f"hip endnode at unexpected depth (expected "
                            f"<hipname>/<endnode>/ when hip_subdir is empty, got {rel})",
                        )
                    )
    return out


# Stubs (Phase 1.5)


def check_i4_segment_count_match(scan: ScanResult) -> list[Violation]:
    """I4 — skeleton.md `segment_count` frontmatter matches actual segment files.

    Only enforced when the skeleton declares `segment_count`. Skeletons without
    the field skip the check (legacy / partial KB units).
    """
    out: list[Violation] = []
    for u in scan.units:
        if u.skeleton is None:
            continue
        fm = read_frontmatter(u.skeleton)
        declared = fm.get("segment_count")
        if declared is None:
            continue
        if not isinstance(declared, int) or declared != len(u.segments):
            out.append(
                Violation(
                    "I4",
                    Severity.CRITICAL,
                    u.skeleton,
                    f"skeleton segment_count={declared!r} but {len(u.segments)} segment files found",
                )
            )
    return out


def check_i5_file_size_caps(scan: ScanResult) -> list[Violation]:
    """I5 — file sizes within MAX_LINES soft caps (warning only)."""
    out: list[Violation] = []
    for u in scan.units:
        for attr, cap_key in (("card", "card"), ("skeleton", "skeleton"),
                              ("dataflow", "dataflow"), ("used_by", "used_by")):
            f = getattr(u, attr)
            if f is None:
                continue
            n = count_lines(f)
            cap = MAX_LINES[cap_key]
            if n > cap:
                out.append(
                    Violation("I5", Severity.WARNING, f, f"{cap_key} has {n} lines (cap {cap})")
                )
        cap_seg = MAX_LINES["segment"]
        for seg in u.segments:
            n = count_lines(seg)
            if n > cap_seg:
                out.append(
                    Violation("I5", Severity.WARNING, seg, f"segment has {n} lines (cap {cap_seg})")
                )
        if u.manifest is not None:
            n = count_lines(u.manifest)
            if n > MANIFEST_WARN_LINES:
                out.append(
                    Violation(
                        "I5",
                        Severity.WARNING,
                        u.manifest,
                        f"manifest has {n} lines (threshold {MANIFEST_WARN_LINES})",
                    )
                )
    return out


def check_i6_dataflow_cross_refs(scan: ScanResult) -> list[Violation]:
    """I6 — dataflow.md cited attribs/groups appear in at least one segment.

    Deferred: requires a stable name-extraction format for dataflow.md (table
    columns? frontmatter list?) that the tracker hasn't standardized yet.
    Returning [] keeps the slot reserved without false positives.
    """
    return []


def check_i7_manifest_segments_match(scan: ScanResult) -> list[Violation]:
    """I7 — HDA manifest.yaml `internal_segments` list length matches segments/."""
    out: list[Violation] = []
    for u in scan.units:
        if u.kind != "hda" or u.manifest is None:
            continue
        try:
            data = yaml.safe_load(u.manifest.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue  # malformed manifest is its own issue, not ours
        declared = data.get("internal_segments")
        if declared is None:
            continue
        if not isinstance(declared, list) or len(declared) != len(u.segments):
            n = len(declared) if isinstance(declared, list) else repr(declared)
            out.append(
                Violation(
                    "I7",
                    Severity.CRITICAL,
                    u.manifest,
                    f"manifest internal_segments count={n} but {len(u.segments)} segment files found",
                )
            )
    return out


def check_i10_used_by_resolve(scan: ScanResult) -> list[Violation]:
    """I10 — used_by.md cited hip paths resolve.

    Deferred: requires git-history awareness to distinguish "stale link"
    from "valid but renamed". Will land alongside the Phase 2 drift hook.
    """
    return []


def check_all_invariants(cfg: AnkrConfig) -> tuple[ScanResult, list[Violation]]:
    """Run every implemented invariant. Returns (scan, violations)."""
    scan = scan_kb(cfg)
    violations: list[Violation] = []
    violations.extend(check_i1_skeleton_present(scan))
    violations.extend(check_i2_no_orphan_segments(scan))
    violations.extend(check_i3_manifest_uniqueness(scan))
    violations.extend(check_i4_segment_count_match(scan))
    violations.extend(check_i5_file_size_caps(scan))
    violations.extend(check_i6_dataflow_cross_refs(scan))
    violations.extend(check_i7_manifest_segments_match(scan))
    violations.extend(check_i8_required_frontmatter(scan))
    violations.extend(check_i9_path_layout(cfg, scan))
    violations.extend(check_i10_used_by_resolve(scan))
    return scan, violations
