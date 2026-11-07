"""Call state machine (003 T048): a call only moves forward, never-connected outcomes happen only
before connecting, and finished calls stay finished."""

from __future__ import annotations

import itertools

import pytest
from callwright_contract.calls import CALL_STATUSES

from app.calls.models import can_transition

LIFE = ["queued", "ringing", "in_progress", "ended", "processing", "completed"]


def test_a_call_moves_forward_through_its_life() -> None:
    assert can_transition(None, "queued")
    assert all(can_transition(a, b) for a, b in itertools.pairwise(LIFE))
    assert can_transition("queued", "in_progress")  # web calls never ring
    assert can_transition("processing", "voicemail")


def test_a_call_never_moves_back() -> None:
    for i, later in enumerate(LIFE):
        assert not any(can_transition(later, earlier) for earlier in LIFE[: i + 1])


@pytest.mark.parametrize("outcome", ["no_answer", "busy", "failed"])
def test_never_connected_outcomes_only_before_connecting(outcome: str) -> None:
    assert can_transition("ringing", outcome)
    assert not any(can_transition(s, outcome) for s in ("in_progress", "ended", "processing"))


def test_refused_calls_are_created_failed() -> None:
    assert can_transition(None, "failed") and can_transition("queued", "failed")
    assert not can_transition(None, "in_progress")


def test_terminal_states_have_no_exit() -> None:
    for terminal in ("completed", "failed", "no_answer", "busy", "voicemail"):
        assert not any(can_transition(terminal, new) for new in CALL_STATUSES)
