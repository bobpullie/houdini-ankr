"""Manifest (manifest.yaml) read/write/update.

Per-hip / per-HDA master index — node hash table + endnode index +
HDA dependency list. The `Manifest` dataclass owns the schema; `save_manifest`
and `load_manifest` provide YAML I/O.

Pure-Python — no Houdini runtime dependency. Used by `ankr track`, `ankr sync`,
and the topology checker.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Manifest:
    hipfile_name: str
    hipfile_current: str
    hipfile_path: str = ""
    last_sync: str = ""
    houdini_version: str = ""
    endnodes: list[dict] = field(default_factory=list)
    nodes: dict[str, dict] = field(default_factory=dict)
    hda_dependencies: list[str] = field(default_factory=list)
    # Plan 2 Task C: HDA tracking discriminator + payload
    kind: str = "hip"  # "hip" | "hda"
    hda_type: str = ""
    hda_modification_time: float = 0.0
    internal_endnode: str = ""
    internal_segments: list[dict] = field(default_factory=list)
    nested_hdas: list[str] = field(default_factory=list)
    # O2: HDA spare parm interface schema (only meaningful when kind == "hda")
    spare_parameters_schema: list[dict] = field(default_factory=list)
    # L0/L1 card system: track previous sync timestamp
    previous_sync: str | None = None
    # B1: per-segment metadata for downstream agent orchestration
    segment_summary: list[dict] = field(default_factory=list)

    def add_endnode(
        self,
        *,
        name: str,
        path: str,
        skeleton: str,
        node_count: int = 0,
        landmark_count: int = 0,
        segment_count: int = 0,
        last_sync: str = "",
    ) -> None:
        self.endnodes = [e for e in self.endnodes if e["name"] != name]
        self.endnodes.append({
            "name": name,
            "path": path,
            "skeleton": skeleton,
            "node_count": node_count,
            "landmark_count": landmark_count,
            "segment_count": segment_count,
            "last_sync": last_sync,
        })

    def upsert_node(
        self,
        path: str,
        type_: str,
        hash_: str,
        referenced_by: list[str],
        flags: Optional[dict] = None,
    ) -> None:
        existing = self.nodes.get(path, {})
        merged_refs = sorted(set(existing.get("referenced_by", [])) | set(referenced_by))
        self.nodes[path] = {
            "hash": hash_,
            "type": type_,
            "referenced_by": merged_refs,
            "flags": dict(flags) if flags else {},
        }

    def remove_node(self, path: str) -> None:
        self.nodes.pop(path, None)

    def add_hda_dependency(self, hda_type: str) -> None:
        if hda_type not in self.hda_dependencies:
            self.hda_dependencies.append(hda_type)

    def diff_against_current(
        self,
        current_hashes: dict[str, str],
        current_flags: Optional[dict[str, dict]] = None,
        restrict_to_endnode: Optional[str] = None,
    ) -> dict:
        """Compare manifest's stored hashes/flags against current runtime state.

        When `restrict_to_endnode` is set, the comparison is scoped to nodes
        that are referenced by that endnode (i.e. any `referenced_by` entry
        starts with `<endnode>/`). This prevents single-endnode sync runs
        from flagging nodes from OTHER endnodes as `deleted`/`added`.
        """
        if restrict_to_endnode:
            prefix = restrict_to_endnode + "/"
            manifest_paths = {
                p for p, info in self.nodes.items()
                if any(ref.startswith(prefix) for ref in info.get("referenced_by", []))
            }
            # Also restrict current_hashes to in-scope nodes (defensive: caller
            # may have dumped a chain that contains foreign nodes).
            current_paths = {p for p in current_hashes.keys() if p in manifest_paths}
        else:
            manifest_paths = set(self.nodes.keys())
            current_paths = set(current_hashes.keys())
        current_flags = current_flags or {}

        added = sorted(current_paths - manifest_paths)
        deleted = sorted(manifest_paths - current_paths)
        changed: list[str] = []
        for p in sorted(manifest_paths & current_paths):
            if self.nodes[p]["hash"] != current_hashes[p]:
                changed.append(p)
                continue
            old_flags = self.nodes[p].get("flags", {}) or {}
            new_flags = current_flags.get(p, {}) or {}
            if old_flags != new_flags:
                changed.append(p)
        return {"changed": changed, "added": added, "deleted": deleted}

    def affected_segments(self, diff: dict) -> set[str]:
        """For a diff result, return all segment IDs that need re-extraction."""
        affected: set[str] = set()
        for path in diff["changed"] + diff["deleted"]:
            if path in self.nodes:
                affected.update(self.nodes[path].get("referenced_by", []))
        return affected


def save_manifest(m: Manifest, path: Path) -> None:
    """Write manifest to yaml file."""
    data = {
        "hipfile_name": m.hipfile_name,
        "hipfile_current": m.hipfile_current,
        "hipfile_path": m.hipfile_path,
        "last_sync": m.last_sync,
        "previous_sync": m.previous_sync,
        "houdini_version": m.houdini_version,
        "kind": m.kind,
        "hda_type": m.hda_type,
        "hda_modification_time": m.hda_modification_time,
        "internal_endnode": m.internal_endnode,
        "internal_segments": m.internal_segments,
        "nested_hdas": m.nested_hdas,
        "spare_parameters_schema": m.spare_parameters_schema,
        "endnodes": m.endnodes,
        "nodes": m.nodes,
        "hda_dependencies": m.hda_dependencies,
        "segment_summary": m.segment_summary,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_manifest(path: Path) -> Optional[Manifest]:
    """Read manifest from yaml file. Return None if not found."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Manifest(
        hipfile_name=data.get("hipfile_name", ""),
        hipfile_current=data.get("hipfile_current", ""),
        hipfile_path=data.get("hipfile_path", ""),
        last_sync=data.get("last_sync", ""),
        previous_sync=data.get("previous_sync"),
        houdini_version=data.get("houdini_version", ""),
        endnodes=data.get("endnodes", []) or [],
        nodes=data.get("nodes", {}) or {},
        hda_dependencies=data.get("hda_dependencies", []) or [],
        kind=data.get("kind", "hip"),
        hda_type=data.get("hda_type", ""),
        hda_modification_time=float(data.get("hda_modification_time", 0.0) or 0.0),
        internal_endnode=data.get("internal_endnode", ""),
        internal_segments=data.get("internal_segments", []) or [],
        nested_hdas=data.get("nested_hdas", []) or [],
        spare_parameters_schema=data.get("spare_parameters_schema", []) or [],
        segment_summary=data.get("segment_summary", []) or [],
    )
