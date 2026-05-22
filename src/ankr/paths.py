"""Single source of truth for every path computed in ANKR.

NO other module may read paths from `ankr.config` directly for filesystem
operations. They must call functions in this module. This indirection is what
guarantees the "zero hardcoded paths" invariant (atlas D2 / Guardrail 1):
if a literal path appears anywhere in code, a single grep finds it.
"""

from __future__ import annotations

from pathlib import Path

from .config import AnkrConfig


def _abs(base: Path, p: Path) -> Path:
    """Return p if absolute, else (base / p) resolved."""
    return p if p.is_absolute() else (base / p).resolve()


def project_root(cfg: AnkrConfig) -> Path:
    return cfg.project.root


def docs_root(cfg: AnkrConfig) -> Path:
    return _abs(cfg.project.root, cfg.docs.root)


def hip_docs_dir(cfg: AnkrConfig) -> Path:
    return docs_root(cfg) / cfg.docs.hip_subdir


def hda_docs_dir(cfg: AnkrConfig) -> Path:
    return docs_root(cfg) / cfg.docs.hda_subdir


def deadflow_reports_dir(cfg: AnkrConfig) -> Path:
    return docs_root(cfg) / cfg.docs.deadflow_reports_subdir


def docs_logs_dir(cfg: AnkrConfig) -> Path:
    return docs_root(cfg) / cfg.docs.logs_subdir


def logs_dir(cfg: AnkrConfig) -> Path:
    return _abs(cfg.project.root, cfg.logging.dir)


def hda_search_paths(cfg: AnkrConfig) -> list[Path]:
    return [_abs(cfg.project.root, p) for p in cfg.hda_search_paths]


def houdini_install_root(cfg: AnkrConfig) -> Path | None:
    return cfg.houdini.install_root


def houdini_user_libs_dir(cfg: AnkrConfig) -> Path | None:
    return cfg.houdini.user_libs_dir


def endnode_doc_dir(cfg: AnkrConfig, endnode_name: str) -> Path:
    """Return docs dir for a hip endnode (`<docs_root>/<hip_subdir>/<endnode>/`)."""
    return hip_docs_dir(cfg) / endnode_name


def hda_doc_dir(cfg: AnkrConfig, hda_folder_name: str) -> Path:
    """Return docs dir for a custom HDA (`<docs_root>/<hda_subdir>/<hda_folder>/`)."""
    return hda_docs_dir(cfg) / hda_folder_name
