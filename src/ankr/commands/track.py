"""`ankr track` — first-track an endnode after a Houdini-side JSON dump.

This subcommand replaces legacy `tools/houdini_graph/scripts/first_track.py`.
Inputs are the four JSON files dumped by `hou_runtime.extract_and_dump`
inside Houdini (chain / segments_enriched / narratives / hashes, plus the
optional landmark_inputs / objpath1 / hda_mtimes files). The subcommand
itself runs from host Python — no `hou` import.

The `docs_root` is read from `ankr.config.yaml` via `paths.docs_root(cfg)`;
the caller does not specify a directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..config import load_config
from ..drivers import first_track
from ..paths import docs_root as _docs_root


def _load(temp: Path, prefix: str, name: str) -> object:
    fname = f"{prefix}_{name}.json" if prefix else f"{name}.json"
    return json.loads((temp / fname).read_text(encoding="utf-8"))


def _load_optional(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run(
    *,
    config_path: Path | None,
    endnode: str,
    hipname: str,
    hip_current: str,
    hip_path: str,
    hou_version: str,
    temp: Path,
    prefix: str,
    hda_mtimes_file: str,
) -> int:
    """Programmatic entry point — return exit code (0 ok, non-zero on error).

    Exposed for tests; the Typer command wraps this.
    """
    cfg = load_config(config_path)
    docs_root = _docs_root(cfg)

    try:
        chain = _load(temp, prefix, "chain")
        enriched = _load(temp, prefix, "segments_enriched")
        narratives = _load(temp, prefix, "narratives")
        hashes_with_flags = _load(temp, prefix, "hashes")
    except FileNotFoundError as e:
        typer.secho(f"ERROR: missing JSON dump in temp dir: {e}", fg=typer.colors.RED, err=True)
        return 2

    hda_mtime_lookup = None
    if hda_mtimes_file:
        mtimes_path = Path(hda_mtimes_file)
        if mtimes_path.exists():
            hda_mtime_lookup = json.loads(mtimes_path.read_text(encoding="utf-8"))

    li_name = f"{prefix}_landmark_inputs.json" if prefix else "landmark_inputs.json"
    op_name = f"{prefix}_objpath1.json" if prefix else "objpath1.json"
    landmark_inputs = _load_optional(temp / li_name)
    objpath1_by_landmark = _load_optional(temp / op_name)

    endnode_name = endnode.rsplit("/", 1)[-1]
    hip_meta = {
        "hipfile_current": hip_current,
        "hipfile_path": hip_path,
        "houdini_version": hou_version,
    }

    result = first_track(
        endnode_path=endnode,
        endnode_name=endnode_name,
        hipname=hipname,
        hip_meta=hip_meta,
        chain=chain,
        enriched=enriched,
        narratives=narratives,
        hashes_with_flags=hashes_with_flags,
        docs_root=docs_root,
        hda_mtime_lookup=hda_mtime_lookup,
        landmark_inputs=landmark_inputs,
        objpath1_by_landmark=objpath1_by_landmark,
    )

    typer.echo(f"manifest mode: {result['manifest_mode']}")
    typer.echo(f"out dir:       {result['out_dir']}")
    typer.echo(f"segments:      {len(result['segment_files'])}")
    typer.echo(f"used_by:       {len(result['used_by_written'])}")
    typer.echo("")
    typer.echo("--- commit bundle (run from docs_root) ---")
    for p in result["commit_bundle"]["paths"]:
        typer.echo(f"  git add {p}")
    typer.echo(f'  git commit -m "{result["commit_bundle"]["message"]}"')

    report = result.get("hda_cache_report") or {}
    if report:
        typer.echo("")
        typer.echo("--- HDA cache report ---")
        for hda, info in sorted(report.items()):
            mark = {"fresh": "✓", "stale": "⚠", "missing": "✗",
                    "unknown": "?"}.get(info["status"], "?")
            typer.echo(f"  {mark} {hda} [{info['status']}]")
        if any(i["status"] in ("stale", "missing") for i in report.values()):
            typer.echo("")
            typer.echo("권장 후속 명령:")
            for hda, info in sorted(report.items()):
                if info["status"] == "missing":
                    typer.echo(f'  - "{hda} HDA 추적해줘"')
                elif info["status"] == "stale":
                    typer.echo(f'  - "{hda} HDA 동기화"')
    return 0


def register(app: typer.Typer) -> None:
    """Register this subcommand on the given Typer app."""

    @app.command(name="track")
    def track(
        endnode: str = typer.Option(
            ...,
            "--endnode",
            help="Endnode path, e.g. /obj/<geo>/OUT_<name>.",
        ),
        hipname: str = typer.Option(
            ...,
            "--hipname",
            help="Hipname folder under docs_root.",
        ),
        hip_current: str = typer.Option(
            ...,
            "--hip-current",
            help="Current hip filename (e.g. SCENE_v001.hiplc).",
        ),
        temp: Path = typer.Option(
            ...,
            "--temp",
            help="Temp dir holding JSON dumps from hou_runtime.extract_and_dump.",
        ),
        config_path: Path = typer.Option(
            None,
            "--config",
            "-c",
            help="Path to ankr.config.yaml. If omitted, walks upward from cwd.",
        ),
        hip_path: str = typer.Option(
            "",
            "--hip-path",
            help="Absolute hip file path on disk (optional, for manifest metadata).",
        ),
        hou_version: str = typer.Option(
            "",
            "--hou-version",
            help="Houdini version string (optional, for manifest metadata).",
        ),
        prefix: str = typer.Option(
            "",
            "--prefix",
            help=("Optional filename prefix for JSON dumps in temp dir "
                  "(e.g. 'kh' → kh_chain.json)."),
        ),
        hda_mtimes_file: str = typer.Option(
            "",
            "--hda-mtimes-file",
            help=("Optional path to a JSON file mapping hda_type → epoch_seconds; "
                  "enables the post-track HDA cache report."),
        ),
    ) -> None:
        """First-track a hip endnode from a JSON dump."""
        code = run(
            config_path=config_path,
            endnode=endnode,
            hipname=hipname,
            hip_current=hip_current,
            hip_path=hip_path,
            hou_version=hou_version,
            temp=temp,
            prefix=prefix,
            hda_mtimes_file=hda_mtimes_file,
        )
        raise typer.Exit(code=code)
