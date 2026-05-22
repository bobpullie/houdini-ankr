"""Tests for `ankr init` and the CLI surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ankr import __version__
from ankr.cli import app
from ankr.config import CONFIG_FILENAME, load_config


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_version_command(runner: CliRunner) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_init_writes_valid_config(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["init", "--project-root", str(tmp_path), "--name", "demo", "--no-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    cfg_path = tmp_path / CONFIG_FILENAME
    assert cfg_path.exists()

    cfg = load_config(cfg_path)
    assert cfg.project.name == "demo"
    assert cfg.project.root == tmp_path
    assert cfg.docs.root == Path("docs/ankr")
    assert cfg.rule_store.kind is None


def test_init_defaults_to_cwd_basename(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--no-interactive"])
    assert result.exit_code == 0, result.stdout
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    assert cfg.project.name == tmp_path.name


def test_init_refuses_to_overwrite_without_force(runner: CliRunner, tmp_path: Path) -> None:
    args = ["init", "--project-root", str(tmp_path), "--name", "x", "--no-interactive"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0
    second = runner.invoke(app, args)
    assert second.exit_code == 1
    assert "already exists" in second.stdout or "already exists" in (second.stderr or "")


def test_init_force_overwrites(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--project-root", str(tmp_path), "--name", "old", "--no-interactive"])
    result = runner.invoke(
        app,
        ["init", "--project-root", str(tmp_path), "--name", "new", "--no-interactive", "--force"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    assert cfg.project.name == "new"


def test_init_rejects_missing_project_root(runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = runner.invoke(app, ["init", "--project-root", str(missing), "--no-interactive"])
    assert result.exit_code == 2


def test_check_on_empty_kb_exits_zero(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--project-root", str(tmp_path), "--name", "p", "--no-interactive"])
    result = runner.invoke(app, ["check", "--config", str(tmp_path / CONFIG_FILENAME)])
    assert result.exit_code == 0
    assert "no violations" in result.stdout


def test_check_json_output(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--project-root", str(tmp_path), "--name", "p", "--no-interactive"])
    result = runner.invoke(app, ["check", "--config", str(tmp_path / CONFIG_FILENAME), "--json"])
    assert result.exit_code == 0
    import json as _json
    payload = _json.loads(result.stdout)
    assert payload["summary"]["critical"] == 0
    assert payload["units"] == []


def test_init_with_houdini_version_hint(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "init",
            "--project-root", str(tmp_path),
            "--name", "h",
            "--houdini-version", "21.0",
            "--no-interactive",
        ],
    )
    assert result.exit_code == 0
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    assert cfg.houdini.version_hint == "21.0"
    # Critical: version_hint must NOT appear in any path field.
    assert "21.0" not in str(cfg.docs.root)
    assert "21.0" not in str(cfg.logging.dir)
