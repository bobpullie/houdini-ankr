"""Tests for `ankr install-to-houdini`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ankr.cli import app
from ankr.commands.install_to_houdini import PACKAGE_NAME, _package_source_dir


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _init_config(
    project_root: Path,
    *,
    user_libs_dir: Path | None = None,
) -> Path:
    """Write a minimal valid ankr.config.yaml; return its path."""
    payload = {
        "ankr_version": "0.1.0",
        "project": {"name": project_root.name, "root": str(project_root)},
        "docs": {"root": "docs/ankr"},
        "houdini": {
            "install_root": None,
            "user_libs_dir": str(user_libs_dir) if user_libs_dir else None,
            "version_hint": None,
        },
    }
    cfg_path = project_root / "ankr.config.yaml"
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    return cfg_path


def test_dry_run_lists_files_without_writing(
    runner: CliRunner, tmp_path: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target_libs = tmp_path / "houdini" / "python3.11libs"
    cfg = _init_config(project, user_libs_dir=target_libs)

    result = runner.invoke(
        app,
        ["install-to-houdini", "--config", str(cfg), "--dry-run"],
    )
    assert result.exit_code == 0, result.stdout
    assert "DRY RUN" in result.stdout
    assert "config.py" in result.stdout  # at least one known module listed
    assert not (target_libs / PACKAGE_NAME).exists()


def test_install_copies_package(runner: CliRunner, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target_libs = tmp_path / "houdini" / "python3.11libs"
    cfg = _init_config(project, user_libs_dir=target_libs)

    result = runner.invoke(
        app,
        ["install-to-houdini", "--config", str(cfg)],
    )
    assert result.exit_code == 0, result.stdout

    installed = target_libs / PACKAGE_NAME
    assert installed.is_dir()
    assert (installed / "__init__.py").exists()
    assert (installed / "config.py").exists()
    assert (installed / "paths.py").exists()
    # __pycache__ excluded
    for d in installed.rglob("__pycache__"):
        pytest.fail(f"__pycache__ should not be installed: {d}")


def test_install_fails_when_user_libs_dir_missing(
    runner: CliRunner, tmp_path: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    cfg = _init_config(project, user_libs_dir=None)

    result = runner.invoke(
        app,
        ["install-to-houdini", "--config", str(cfg)],
    )
    assert result.exit_code != 0
    assert "user_libs_dir" in (result.stdout + (result.stderr or ""))


def test_install_refuses_overwrite_without_force(
    runner: CliRunner, tmp_path: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target_libs = tmp_path / "houdini" / "python3.11libs"
    cfg = _init_config(project, user_libs_dir=target_libs)

    first = runner.invoke(app, ["install-to-houdini", "--config", str(cfg)])
    assert first.exit_code == 0
    second = runner.invoke(app, ["install-to-houdini", "--config", str(cfg)])
    assert second.exit_code == 1
    assert "exists" in (second.stdout + (second.stderr or ""))


def test_install_force_overwrites(runner: CliRunner, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target_libs = tmp_path / "houdini" / "python3.11libs"
    cfg = _init_config(project, user_libs_dir=target_libs)

    runner.invoke(app, ["install-to-houdini", "--config", str(cfg)])
    # Stick a sentinel file into the target — it must vanish after --force.
    sentinel = target_libs / PACKAGE_NAME / "sentinel.txt"
    sentinel.write_text("legacy", encoding="utf-8")
    assert sentinel.exists()

    result = runner.invoke(
        app, ["install-to-houdini", "--config", str(cfg), "--force"]
    )
    assert result.exit_code == 0, result.stdout
    assert not sentinel.exists()


def test_package_source_dir_resolves_to_ankr(tmp_path: Path) -> None:
    src = _package_source_dir()
    assert src.name == "ankr"
    assert (src / "config.py").exists()
