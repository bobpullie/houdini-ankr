"""Tests for ankr.config — schema validation, env expansion, search-upward."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ankr.config import AnkrConfig, CONFIG_FILENAME, load_config


def _minimal_raw(project_root: Path) -> dict:
    return {
        "ankr_version": "0.1.0",
        "project": {"name": "test", "root": str(project_root)},
    }


def test_minimal_config_validates(tmp_path: Path) -> None:
    cfg = AnkrConfig.model_validate(_minimal_raw(tmp_path))
    assert cfg.project.root == tmp_path
    assert cfg.docs.root == Path("docs/ankr")
    assert cfg.rule_store.kind is None
    assert cfg.hooks.enable_drift_reminder is True


def test_project_root_must_be_absolute(tmp_path: Path) -> None:
    raw = _minimal_raw(tmp_path)
    raw["project"]["root"] = "relative/path"
    with pytest.raises(ValidationError, match="must be absolute"):
        AnkrConfig.model_validate(raw)


def test_load_from_explicit_path(tmp_path: Path) -> None:
    cfg_path = tmp_path / CONFIG_FILENAME
    cfg_path.write_text(yaml.safe_dump(_minimal_raw(tmp_path)), encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.project.name == "test"


def test_load_searches_upward(tmp_path: Path) -> None:
    cfg_path = tmp_path / CONFIG_FILENAME
    cfg_path.write_text(yaml.safe_dump(_minimal_raw(tmp_path)), encoding="utf-8")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    cfg = load_config(search_from=nested)
    assert cfg.project.root == tmp_path


def test_load_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No ankr.config.yaml found"):
        load_config(search_from=tmp_path)


def test_env_var_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_ROOT", str(tmp_path))
    raw = {
        "ankr_version": "0.1.0",
        "project": {"name": "test", "root": "${MY_ROOT}"},
    }
    cfg_path = tmp_path / CONFIG_FILENAME
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.project.root == tmp_path


def test_unresolved_envvar_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    raw = {
        "ankr_version": "0.1.0",
        "project": {"name": "test", "root": "${DEFINITELY_NOT_SET}"},
    }
    cfg_path = tmp_path / CONFIG_FILENAME
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_config(cfg_path)
