"""Tests for ankr.rule_store — default no-op + adapter Protocol."""

from __future__ import annotations

from ankr.config import RuleStoreConfig
from ankr.rule_store import NullRuleStore, RuleStore, load_rule_store


def test_null_rule_store_is_unavailable() -> None:
    s = NullRuleStore()
    assert s.is_available() is False
    s.write_candidate(rule="x", triggers=[], tags=[], evidence="")  # must not raise


def test_default_factory_returns_null() -> None:
    s = load_rule_store(RuleStoreConfig())
    assert isinstance(s, NullRuleStore)


def test_unknown_kind_falls_back_to_null() -> None:
    s = load_rule_store(RuleStoreConfig(kind="tems", config={}))
    assert isinstance(s, NullRuleStore)


def test_null_satisfies_protocol() -> None:
    assert isinstance(NullRuleStore(), RuleStore)
