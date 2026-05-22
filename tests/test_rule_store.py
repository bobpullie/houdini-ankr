"""Tests for ankr.rule_store — default no-op + adapter Protocol."""

from __future__ import annotations

import warnings

import pytest

from ankr.config import RuleStoreConfig
from ankr.rule_store import NullRuleStore, RuleStore, load_rule_store


def test_null_rule_store_is_unavailable() -> None:
    s = NullRuleStore()
    assert s.is_available() is False
    s.write_candidate(rule="x", triggers=[], tags=[], evidence="")  # must not raise


def test_default_factory_returns_null() -> None:
    s = load_rule_store(RuleStoreConfig())
    assert isinstance(s, NullRuleStore)


def test_unknown_kind_falls_back_to_null_with_warning() -> None:
    """Typos like `kind: tmes` must not silently disable the rule store."""
    with pytest.warns(UserWarning, match="Unknown rule_store.kind"):
        s = load_rule_store(RuleStoreConfig(kind="tmes", config={}))
    assert isinstance(s, NullRuleStore)


def test_default_kind_none_emits_no_warning() -> None:
    """The intentional no-op default must not nag."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # promote all warnings to errors
        s = load_rule_store(RuleStoreConfig())
    assert isinstance(s, NullRuleStore)


def test_null_satisfies_protocol() -> None:
    assert isinstance(NullRuleStore(), RuleStore)


def test_duck_typed_adapter_satisfies_protocol() -> None:
    """Hand-rolled adapter (not subclassing) passes isinstance check."""

    class HandRolled:
        def write_candidate(self, *, rule: str, triggers: list[str],
                            tags: list[str], evidence: str) -> None:
            return None

        def is_available(self) -> bool:
            return True

    assert isinstance(HandRolled(), RuleStore)
