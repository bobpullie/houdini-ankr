"""Tests for the HDA cache lookup module."""
from pathlib import Path

from ankr.hda_cache import (
    safe_hda_id,
    hda_manifest_path,
    lookup_hda_cache,
    bulk_lookup,
)
from ankr.manifest import Manifest, save_manifest


def test_safe_hda_id_replaces_double_colons():
    assert safe_hda_id("bluei::KJI_SharpPoints_Bevel::1.2") == \
        "bluei__KJI_SharpPoints_Bevel__1.2"


def test_safe_hda_id_handles_no_namespace():
    """An HDA without a namespace (just `name::ver`) should still be
    safely encoded."""
    assert safe_hda_id("nonamespace::1.0") == "nonamespace__1.0"


def test_hda_manifest_path_under_custom_hda(tmp_path: Path):
    p = hda_manifest_path(tmp_path, "bluei::KJI_SharpPoints_Bevel::1.2")
    assert p == tmp_path / "custom_hda" / "bluei__KJI_SharpPoints_Bevel__1.2" / "manifest.yaml"


def _write_hda_manifest(tmp_path: Path, hda_type: str, mtime: float) -> Path:
    """Helper: write a kind=hda manifest to the right location."""
    safe = hda_type.replace("::", "__")
    target = tmp_path / "custom_hda" / safe / "manifest.yaml"
    m = Manifest(
        hipfile_name=hda_type,
        hipfile_current=f"{safe}.hdalc",
        kind="hda",
        hda_type=hda_type,
        hda_modification_time=mtime,
        internal_endnode="output0",
    )
    save_manifest(m, target)
    return target


def test_lookup_returns_missing_when_no_manifest(tmp_path: Path):
    status, m = lookup_hda_cache(tmp_path, "bluei::Foo::1.0", current_mtime=1000.0)
    assert status == "missing"
    assert m is None


def test_lookup_returns_fresh_when_mtime_matches(tmp_path: Path):
    _write_hda_manifest(tmp_path, "bluei::Foo::1.0", mtime=1000.0)
    status, m = lookup_hda_cache(tmp_path, "bluei::Foo::1.0", current_mtime=1000.0)
    assert status == "fresh"
    assert m is not None
    assert m.hda_modification_time == 1000.0


def test_lookup_returns_stale_when_mtime_differs(tmp_path: Path):
    _write_hda_manifest(tmp_path, "bluei::Foo::1.0", mtime=1000.0)
    status, m = lookup_hda_cache(tmp_path, "bluei::Foo::1.0", current_mtime=2000.0)
    assert status == "stale"
    assert m is not None


def test_lookup_tolerates_subsecond_drift(tmp_path: Path):
    """Filesystem mtime is often only second-precise. Default tolerance
    is 1.0 seconds — sub-second drift must NOT trigger stale."""
    _write_hda_manifest(tmp_path, "bluei::Foo::1.0", mtime=1000.0)
    status, _ = lookup_hda_cache(tmp_path, "bluei::Foo::1.0", current_mtime=1000.4)
    assert status == "fresh"


def test_lookup_treats_hip_kind_manifest_as_missing(tmp_path: Path):
    """Defensive: if a hip-kind manifest accidentally lives at the HDA
    cache path, lookup must NOT treat it as a fresh HDA cache hit."""
    safe = "bluei__Foo__1.0"
    target = tmp_path / "custom_hda" / safe / "manifest.yaml"
    bad = Manifest(
        hipfile_name="bluei::Foo::1.0",
        hipfile_current="X.hip",
        kind="hip",
    )
    save_manifest(bad, target)
    status, _ = lookup_hda_cache(tmp_path, "bluei::Foo::1.0", current_mtime=1000.0)
    assert status == "missing"


def test_bulk_lookup_classifies_three_states(tmp_path: Path):
    _write_hda_manifest(tmp_path, "bluei::Fresh::1.0", mtime=1000.0)
    _write_hda_manifest(tmp_path, "bluei::Stale::1.0", mtime=500.0)
    # bluei::Missing::1.0 has no manifest

    queries = {
        "bluei::Fresh::1.0":   1000.0,
        "bluei::Stale::1.0":   1500.0,
        "bluei::Missing::1.0": 9999.0,
    }
    results = bulk_lookup(tmp_path, queries)
    assert set(results.keys()) == set(queries.keys())
    assert results["bluei::Fresh::1.0"][0]   == "fresh"
    assert results["bluei::Stale::1.0"][0]   == "stale"
    assert results["bluei::Missing::1.0"][0] == "missing"
