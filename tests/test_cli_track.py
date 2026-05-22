"""Tests for `ankr track` subcommand wiring.

The driver itself is covered by `test_drivers.py`. These tests confirm:
1. `ankr track --help` registers the subcommand.
2. `run()` loads docs_root from cfg and pipes JSON inputs through `first_track`.
3. Missing JSON dump → exit 2 with a clear error.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ankr.cli import app
from ankr.commands.track import run as track_run


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _init_config(project_root: Path, *, docs_root: str = "docs/ankr") -> Path:
    payload = {
        "ankr_version": "0.1.0",
        "project": {"name": project_root.name, "root": str(project_root)},
        "docs": {"root": docs_root, "hip_subdir": "", "hda_subdir": "custom_hda"},
    }
    cfg_path = project_root / "ankr.config.yaml"
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    return cfg_path


def _write_minimal_dumps(temp_dir: Path, prefix: str = "") -> None:
    """Write the four mandatory JSON dumps for a 1-node chain."""
    prefix_part = f"{prefix}_" if prefix else ""
    chain = [
        {"name": "OUT_X", "type": "null", "path": "/obj/X/OUT_X",
         "is_hda": False, "hda_type": ""},
    ]
    enriched = [{
        "seg_id": "seg_01_out_x",
        "nodes": [{
            "name": "OUT_X", "type": "null", "path": "/obj/X/OUT_X",
            "is_hda": False, "kind": "passthrough", "flags": {},
            "params_non_default": {}, "random_seeds": [],
        }],
    }]
    narratives = {"seg_01_out_x": {"data": {}, "narrative": "test"}}
    hashes = {"/obj/X/OUT_X": {"hash": "h_out", "flags": {}}}

    (temp_dir / f"{prefix_part}chain.json").write_text(
        json.dumps(chain), encoding="utf-8")
    (temp_dir / f"{prefix_part}segments_enriched.json").write_text(
        json.dumps(enriched), encoding="utf-8")
    (temp_dir / f"{prefix_part}narratives.json").write_text(
        json.dumps(narratives), encoding="utf-8")
    (temp_dir / f"{prefix_part}hashes.json").write_text(
        json.dumps(hashes), encoding="utf-8")


def test_track_help_registered(runner: CliRunner) -> None:
    result = runner.invoke(app, ["track", "--help"])
    assert result.exit_code == 0
    assert "First-track a hip endnode" in result.output


def test_track_run_writes_skeleton_under_docs_root(tmp_path: Path) -> None:
    cfg_path = _init_config(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    _write_minimal_dumps(temp_dir)

    code = track_run(
        config_path=cfg_path,
        endnode="/obj/X/OUT_X",
        hipname="TEST_HIP",
        hip_current="TEST.hiplc",
        hip_path="",
        hou_version="21.0.671",
        temp=temp_dir,
        prefix="",
        hda_mtimes_file="",
    )
    assert code == 0
    docs_root = tmp_path / "docs" / "ankr"
    assert (docs_root / "TEST_HIP" / "OUT_X" / "skeleton.md").exists()
    assert (docs_root / "TEST_HIP" / "manifest.yaml").exists()


def test_track_run_returns_2_on_missing_dump(tmp_path: Path) -> None:
    cfg_path = _init_config(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    # no JSON files written

    code = track_run(
        config_path=cfg_path,
        endnode="/obj/X/OUT_X",
        hipname="TEST_HIP",
        hip_current="TEST.hiplc",
        hip_path="",
        hou_version="21.0.671",
        temp=temp_dir,
        prefix="",
        hda_mtimes_file="",
    )
    assert code == 2


def test_track_run_honors_prefix(tmp_path: Path) -> None:
    cfg_path = _init_config(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    _write_minimal_dumps(temp_dir, prefix="kh")

    code = track_run(
        config_path=cfg_path,
        endnode="/obj/X/OUT_X",
        hipname="TEST_HIP",
        hip_current="TEST.hiplc",
        hip_path="",
        hou_version="21.0.671",
        temp=temp_dir,
        prefix="kh",
        hda_mtimes_file="",
    )
    assert code == 0
