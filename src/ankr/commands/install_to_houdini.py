"""`ankr install-to-houdini` — copy the `ankr` package into Houdini's user libs.

This subcommand replaces legacy `tools/houdini_graph/scripts/install_to_houdini.py`.
Source = wherever the `ankr` package is installed in the host Python environment.
Target = `houdini.user_libs_dir / "ankr"` from `ankr.config.yaml`.

The target Houdini installation must be told where its `python3.11libs/` lives
via the `houdini.user_libs_dir` config key — ANKR refuses to guess machine-
specific paths (atlas guardrail 1: zero hardcoded paths).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from .. import __version__
from ..config import AnkrConfig, load_config
from ..paths import houdini_user_libs_dir

PACKAGE_NAME = "ankr"


def _package_source_dir() -> Path:
    """Return the directory containing the installed `ankr` package."""
    return Path(__file__).resolve().parent.parent


def _collect_files(source: Path) -> list[Path]:
    return sorted(
        p
        for p in source.rglob("*.py")
        if "__pycache__" not in p.parts and not p.name.endswith(".pyc")
    )


def _resolve_target(cfg: AnkrConfig) -> Path:
    libs_dir = houdini_user_libs_dir(cfg)
    if libs_dir is None:
        raise typer.BadParameter(
            "houdini.user_libs_dir is not set in ankr.config.yaml. "
            "Set it to the Houdini user prefs python libs directory "
            "(e.g. ~/Documents/houdini21.0/python3.11libs) and retry."
        )
    return Path(libs_dir) / PACKAGE_NAME


def run(
    *,
    config_path: Path | None,
    dry_run: bool,
    force: bool,
    echo: typer.Typer | None = None,
) -> int:
    """Programmatic entry point — return exit code (0 ok, non-zero on error).

    Exposed for tests; the Typer command wraps this.
    """
    cfg = load_config(config_path)
    source = _package_source_dir()
    target = _resolve_target(cfg)

    if not source.exists():
        typer.secho(f"ERROR: source not found: {source}", fg=typer.colors.RED, err=True)
        return 1

    files = _collect_files(source)

    if dry_run:
        typer.echo(f"[DRY RUN] Would install {len(files)} .py files")
        typer.echo(f"  ankr version: {__version__}")
        typer.echo(f"  source: {source}")
        typer.echo(f"  target: {target}")
        for f in files:
            typer.echo(f"    {f.relative_to(source)}")
        return 0

    if target.exists() and not force:
        typer.secho(
            f"target already exists: {target}\nUse --force to overwrite.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    installed = sorted(p.relative_to(target) for p in target.rglob("*.py"))
    typer.secho(f"Installed {len(installed)} files to: {target}", fg=typer.colors.GREEN)
    return 0


def register(app: typer.Typer) -> None:
    """Register this subcommand on the given Typer app."""

    @app.command(name="install-to-houdini")
    def install_to_houdini(
        config_path: Path = typer.Option(
            None,
            "--config",
            "-c",
            help="Path to ankr.config.yaml. If omitted, walks upward from cwd.",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="List files that would be installed without writing.",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Overwrite an existing ankr package at the target.",
        ),
    ) -> None:
        """Install the `ankr` package into Houdini's user python libs."""
        code = run(config_path=config_path, dry_run=dry_run, force=force)
        raise typer.Exit(code=code)
