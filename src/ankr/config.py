"""Configuration schema and loader for ANKR.

The schema is the single source of truth for every path and every behavioral
flag in the plugin. No module in `ankr` may read a path literal or environment
variable directly — all access goes through a loaded `AnkrConfig` instance,
typically via `ankr.paths`.

Schema v1 (load-bearing — see atlas D2, D7, D8).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Schema models
# ---------------------------------------------------------------------------


class ProjectConfig(BaseModel):
    name: str = Field(..., description="Project name; defaults to project.root basename if omitted at init time.")
    root: Path = Field(..., description="Absolute path to the project root. Resolved at `ankr init` time.")

    @field_validator("root")
    @classmethod
    def _root_must_be_absolute(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"project.root must be absolute, got: {v}")
        return v


class DocsConfig(BaseModel):
    root: Path = Field(
        default=Path("docs/ankr"),
        description="KB output root. Relative paths are resolved against project.root.",
    )
    hip_subdir: str = "hip"
    hda_subdir: str = "custom_hda"
    deadflow_reports_subdir: str = "deadflow_reports"
    logs_subdir: str = "logs"


class HoudiniConfig(BaseModel):
    install_root: Path | None = Field(
        default=None,
        description="Houdini install root. If null, ANKR will best-effort auto-detect via HFS env var.",
    )
    user_libs_dir: Path | None = Field(
        default=None,
        description="Target dir for `ankr install-to-houdini`. If null, derived from version_hint and OS user prefs.",
    )
    version_hint: str | None = Field(
        default=None,
        description="Informational only (e.g. '21.0'). NEVER used as a path literal in code.",
    )


class LoggingConfig(BaseModel):
    dir: Path = Field(
        default=Path("logs/ankr"),
        description="Log directory. Relative paths resolved against project.root.",
    )
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class RuleStoreConfig(BaseModel):
    """Pluggable rule store for Phase 3 `promote-check`.

    The default `kind: null` means no rule store is wired — `promote-check`
    becomes a no-op that just prints candidates. Users who want integration
    with their own memory system (e.g. TEMS) write an adapter and set
    `kind: <adapter_name>` with adapter-specific `config`.

    ANKR core code MUST NOT depend on any specific `kind` value.
    """

    kind: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class HooksConfig(BaseModel):
    enable_drift_reminder: bool = True
    enable_session_end_check: bool = True


class AnkrConfig(BaseModel):
    """Top-level ANKR config. Loaded from `ankr.config.yaml` in project root."""

    ankr_version: str = Field(default="0.1.0", description="Config schema version, not plugin version.")
    project: ProjectConfig
    docs: DocsConfig = Field(default_factory=DocsConfig)
    houdini: HoudiniConfig = Field(default_factory=HoudiniConfig)
    hda_search_paths: list[Path] = Field(
        default_factory=list,
        description="Additional .hda dirs for resolution. Absolute or relative-to-project.root.",
    )
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    rule_store: RuleStoreConfig = Field(default_factory=RuleStoreConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)

    @model_validator(mode="after")
    def _check_no_unresolved_envvars(self) -> "AnkrConfig":
        for field_name in ("project", "docs", "houdini", "logging"):
            section = getattr(self, field_name)
            for k, v in section.model_dump().items():
                if isinstance(v, str) and "${" in v:
                    raise ValueError(
                        f"Unresolved env var placeholder in {field_name}.{k}: {v!r}. "
                        "Env-var expansion happens in `load_config`; reaching the model "
                        "with `${...}` left in means resolution failed."
                    )
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


CONFIG_FILENAME = "ankr.config.yaml"


def _expand_env(value: Any) -> Any:
    """Recursively expand `${VAR}` references in strings using os.environ."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def load_config(config_path: Path | str | None = None, *, search_from: Path | None = None) -> AnkrConfig:
    """Load and validate an ANKR config from disk.

    Resolution order:
    1. Explicit `config_path` if given.
    2. `ANKR_CONFIG` env var.
    3. Walk up from `search_from` (or cwd) looking for `ankr.config.yaml`.

    Raises:
        FileNotFoundError: if no config is found.
        pydantic.ValidationError: if the file is malformed.
    """
    path = _resolve_config_path(config_path, search_from=search_from)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    raw = _expand_env(raw)
    return AnkrConfig.model_validate(raw)


def _resolve_config_path(
    config_path: Path | str | None,
    *,
    search_from: Path | None,
) -> Path:
    if config_path is not None:
        p = Path(config_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"ANKR config not found at explicit path: {p}")
        return p

    env = os.environ.get("ANKR_CONFIG")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"ANKR_CONFIG env var points to missing file: {p}")
        return p

    start = (search_from or Path.cwd()).resolve()
    for d in (start, *start.parents):
        candidate = d / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No {CONFIG_FILENAME} found. Searched from {start} upward. "
        f"Run `ankr init` in your project root to create one."
    )
