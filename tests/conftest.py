"""Shared pytest fixtures.

P1.6 Wave 4: the `mock_card_step` autouse fixture patches the hip-only
driver entry points (`_hip` and `_shared_steps`). When the HDA driver
(`_hda`) is ported in T4, a third patch site is added here.
"""
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_card_step():
    """Auto-mock prepare_card_step so existing tests aren't affected by card integration."""
    mock_rv = {"status": "skipped", "reason": "test_mock"}
    with (
        patch("ankr.drivers._hip.prepare_card_step", return_value=mock_rv),
        patch("ankr.drivers._shared_steps.prepare_card_step", return_value=mock_rv),
    ):
        yield
