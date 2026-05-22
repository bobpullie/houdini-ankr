"""ANKR command-line interface.

Single entrypoint: `ankr <subcommand>`. All future commands hang off this.

Phase 0 ships: `init`, `version`.
Phase 1+ will add: `check`, `track`, `sync`, `scan`, `split`, `collapse`,
`backfill`, `promote-check`, `rebuild`, `init-skill`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
import yaml

from . import __version__
from .commands import install_to_houdini as _install_to_houdini
from .commands import track as _track
from .config import CONFIG_FILENAME, AnkrConfig, load_config
from .topology import Severity, check_all_invariants

app = typer.Typer(
    name="ankr",
    help="ANKR — Agent Network Knowledge Reader. Hierarchical KB for SideFX Houdini networks.",
    no_args_is_help=True,
    add_completion=False,
)

_install_to_houdini.register(app)
_track.register(app)


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print plugin version and exit."""
    typer.echo(f"houdini-ankr {__version__}")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def _default_project_root() -> Path:
    return Path.cwd().resolve()


def _build_config_dict(
    *,
    project_name: str,
    project_root: Path,
    docs_root: str,
    houdini_version_hint: str | None,
    interactive: bool,
) -> dict:
    """Construct the YAML payload — keep keys in user-friendly order."""
    return {
        "ankr_version": "0.1.0",
        "project": {
            "name": project_name,
            "root": str(project_root),
        },
        "docs": {
            "root": docs_root,
            "hip_subdir": "",
            "hda_subdir": "custom_hda",
            "deadflow_reports_subdir": "deadflow_reports",
            "logs_subdir": "logs",
        },
        "houdini": {
            "install_root": None,
            "user_libs_dir": None,
            "version_hint": houdini_version_hint,
        },
        "hda_search_paths": [],
        "logging": {
            "dir": "logs/ankr",
            "level": "INFO",
        },
        "rule_store": {
            "kind": None,
            "config": {},
        },
        "hooks": {
            "enable_drift_reminder": True,
            "enable_session_end_check": True,
        },
    }


def _prompt_if_missing(
    label: str,
    value: str | None,
    default: str | None,
    interactive: bool,
) -> str:
    if value is not None:
        return value
    if not interactive:
        if default is None:
            typer.secho(f"--{label} is required in non-interactive mode", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        return default
    return typer.prompt(label, default=default)


@app.command()
def init(
    project_root: Path = typer.Option(
        None,
        "--project-root",
        "-p",
        help="Absolute path to the project root. Default: current working directory.",
    ),
    project_name: str = typer.Option(
        None,
        "--name",
        "-n",
        help="Project name. Default: project_root basename.",
    ),
    docs_root: str = typer.Option(
        None,
        "--docs-root",
        "-d",
        help="KB output root. Default: 'docs/ankr' (relative to project root).",
    ),
    houdini_version_hint: str = typer.Option(
        None,
        "--houdini-version",
        help="Informational only (e.g. '21.0'). Never used as a path literal.",
    ),
    no_interactive: bool = typer.Option(
        False,
        "--no-interactive",
        help="Fail instead of prompting when a required value is missing.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing ankr.config.yaml.",
    ),
    repair: bool = typer.Option(
        False,
        "--repair",
        help="Re-write config preserving any explicitly provided values; same effect as --force for now.",
    ),
) -> None:
    """Scaffold an `ankr.config.yaml` in the target project root.

    Flag-driven first; any required value not provided is prompted interactively
    unless `--no-interactive` is set.
    """
    interactive = not no_interactive

    resolved_root = (project_root or _default_project_root()).expanduser().resolve()
    if not resolved_root.is_absolute():
        typer.secho(f"project-root must resolve to an absolute path: {resolved_root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if not resolved_root.exists():
        typer.secho(f"project-root does not exist: {resolved_root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    target = resolved_root / CONFIG_FILENAME
    if target.exists() and not (force or repair):
        typer.secho(
            f"{CONFIG_FILENAME} already exists at {target}. Use --force or --repair to overwrite.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=1)

    name = _prompt_if_missing("name", project_name, resolved_root.name, interactive)
    docs = _prompt_if_missing("docs-root", docs_root, "docs/ankr", interactive)

    payload = _build_config_dict(
        project_name=name,
        project_root=resolved_root,
        docs_root=docs,
        houdini_version_hint=houdini_version_hint,
        interactive=interactive,
    )

    # Validate before writing — fail fast if our own builder produces a bad dict.
    AnkrConfig.model_validate(payload)

    with target.open("w", encoding="utf-8") as f:
        f.write(
            "# ankr.config.yaml — generated by `ankr init`.\n"
            "# Edit by hand or re-run `ankr init --repair`.\n"
            "# Do NOT commit machine-specific paths; prefer ${ENV_VARS}.\n\n"
        )
        yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    typer.secho(f"Wrote {target}", fg=typer.colors.GREEN)
    typer.echo("Next: edit the file, then run `ankr check` (Phase 1) once available.")


# ---------------------------------------------------------------------------
# check (Phase 1 stub)
# ---------------------------------------------------------------------------


@app.command()
def check(
    config_path: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to ankr.config.yaml. If omitted, walks upward from cwd.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of human-readable summary.",
    ),
) -> None:
    """Run topology invariants I1~I10 over the configured KB.

    Exit code:
      0  no critical violations
      1  one or more critical violations

    Warnings do not change exit code.
    """
    import json as _json

    cfg = load_config(config_path)
    scan, violations = check_all_invariants(cfg)

    critical = [v for v in violations if v.severity == Severity.CRITICAL]
    warnings = [v for v in violations if v.severity == Severity.WARNING]

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "docs_root": str(scan.docs_root),
                    "units": [{"kind": u.kind, "root": str(u.root)} for u in scan.units],
                    "violations": [v.to_dict() for v in violations],
                    "summary": {
                        "critical": len(critical),
                        "warning": len(warnings),
                        "units": len(scan.units),
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        typer.echo(f"docs_root: {scan.docs_root}")
        typer.echo(f"units:     {len(scan.units)} ({sum(1 for u in scan.units if u.kind == 'hip')} hip, "
                   f"{sum(1 for u in scan.units if u.kind == 'hda')} hda)")
        if not violations:
            typer.secho("✓ no violations", fg=typer.colors.GREEN)
        else:
            for v in violations:
                color = typer.colors.RED if v.severity == Severity.CRITICAL else typer.colors.YELLOW
                typer.secho(f"  [{v.invariant_id}] {v.severity.value}: {v.path} — {v.message}", fg=color)
            typer.echo(f"\nsummary: {len(critical)} critical, {len(warnings)} warning")

    raise typer.Exit(code=1 if critical else 0)


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Console-script entrypoint (`ankr` in pyproject.toml)."""
    app()


if __name__ == "__main__":
    main()
    sys.exit(0)
