"""Shared pytest fixtures.

The `mock_card_step` fixture stubs `prepare_card_step` so most tests don't
need to set up card prerequisites. Both `_hip` and `_shared_steps` import
sites are patched (the `_shared_steps` site also covers the future hda
flow once P1.6 T4 unlocks it — no third patch site needed because hda
dispatches through the same `prepare_card_step` import).

The fixture yields the two `MagicMock` instances so tests CAN verify that
`prepare_card_step` was actually invoked, by accepting `mock_card_step`
as a parameter and inspecting `.called` / `.call_count` / `.call_args`.
Existing tests that don't request the parameter still get the autouse
patch transparently.
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_card_step():
    """Auto-mock `prepare_card_step` and yield the mocks for inspection.

    Yields:
        (hip_mock, shared_mock): MagicMock instances bound to the two
        import sites. Tests that want to verify call patterns request
        this fixture by parameter; tests that just need the stub return
        do nothing — the patch is active either way.
    """
    mock_rv = {"status": "skipped", "reason": "test_mock"}
    hip_mock = MagicMock(return_value=mock_rv)
    shared_mock = MagicMock(return_value=mock_rv)
    with (
        patch("ankr.drivers._hip.prepare_card_step", new=hip_mock),
        patch("ankr.drivers._shared_steps.prepare_card_step", new=shared_mock),
    ):
        yield hip_mock, shared_mock
