"""Tests for ankr.paths — every path goes through this module."""

from __future__ import annotations

from pathlib import Path

from ankr import paths
from ankr.config import AnkrConfig


def _cfg(project_root: Path, **overrides) -> AnkrConfig:
    raw = {
        "ankr_version": "0.1.0",
        "project": {"name": "t", "root": str(project_root)},
    }
    raw.update(overrides)
    return AnkrConfig.model_validate(raw)


def test_docs_root_default_relative_to_project(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert paths.docs_root(cfg) == tmp_path / "docs" / "ankr"


def test_docs_root_absolute_override(tmp_path: Path) -> None:
    abs_docs = tmp_path / "elsewhere" / "docs"
    cfg = _cfg(tmp_path, docs={"root": str(abs_docs)})
    assert paths.docs_root(cfg) == abs_docs


def test_subdir_helpers(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    # hip_subdir default "" — hip endnodes live at <docs_root>/<hipname>/<endnode>/
    assert paths.hip_docs_dir(cfg) == tmp_path / "docs" / "ankr"
    assert paths.hda_docs_dir(cfg) == tmp_path / "docs" / "ankr" / "custom_hda"
    assert paths.deadflow_reports_dir(cfg) == tmp_path / "docs" / "ankr" / "deadflow_reports"
    assert paths.docs_logs_dir(cfg) == tmp_path / "docs" / "ankr" / "logs"


def test_hip_subdir_explicit(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, docs={"root": "docs/ankr", "hip_subdir": "hip"})
    assert paths.hip_docs_dir(cfg) == tmp_path / "docs" / "ankr" / "hip"


def test_logs_dir_default(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert paths.logs_dir(cfg) == tmp_path / "logs" / "ankr"


def test_endnode_doc_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    # default hip_subdir="" places endnode under <docs_root>/<endnode>/
    assert paths.endnode_doc_dir(cfg, "AI_EndNode") == tmp_path / "docs" / "ankr" / "AI_EndNode"


def test_hda_doc_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert paths.hda_doc_dir(cfg, "blueitems__KJI_GradientSlice__1.0") == (
        tmp_path / "docs" / "ankr" / "custom_hda" / "blueitems__KJI_GradientSlice__1.0"
    )


def test_hda_search_paths_resolved(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, hda_search_paths=["hda/local", str(tmp_path / "abs" / "hda")])
    result = paths.hda_search_paths(cfg)
    assert result[0] == tmp_path / "hda" / "local"
    assert result[1] == tmp_path / "abs" / "hda"
