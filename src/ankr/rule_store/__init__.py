"""Pluggable rule-store interface.

ANKR ships fully self-contained. The optional `RuleStore` Protocol exists so
Phase 3 `promote-check` can write TGL-style candidates somewhere — but the
default is `NullRuleStore` (a no-op). Wiring to any specific memory system
(e.g. TEMS) lives in user-provided adapter modules, never in ANKR core.

Atlas D1 / Guardrail 2: ANKR core MUST NOT import any concrete adapter.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import RuleStoreConfig


@runtime_checkable
class RuleStore(Protocol):
    """Minimal contract for a rule store. Adapters implement this."""

    def write_candidate(
        self,
        *,
        rule: str,
        triggers: list[str],
        tags: list[str],
        evidence: str,
    ) -> None:
        """Persist a candidate promotion. Implementations may be sync or async-wrapped."""
        ...

    def is_available(self) -> bool:
        """Return True if the backing store is reachable; False to gracefully no-op."""
        ...


class NullRuleStore:
    """Default no-op implementation. Always 'unavailable'."""

    def write_candidate(self, **_kwargs: object) -> None:
        return None

    def is_available(self) -> bool:
        return False


def load_rule_store(cfg: RuleStoreConfig) -> RuleStore:
    """Factory: return the configured RuleStore, or NullRuleStore if none/unknown.

    Adapter resolution is intentionally string-based and lazy-imported so ANKR
    core has no compile-time dependency on any specific adapter package.
    """
    if cfg.kind is None:
        return NullRuleStore()

    # Lazy-import path: adapters live in `ankr_rule_store_<kind>` external
    # packages (entry-point discovery is a Phase 3 concern). For now, unknown
    # kinds fall back to NullRuleStore with a soft warning emitted by callers.
    return NullRuleStore()
