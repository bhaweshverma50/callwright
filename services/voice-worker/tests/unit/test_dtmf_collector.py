"""T094: keypad collector (research R11, FR-021)."""

from __future__ import annotations

import pytest

from tests.harness.clock import VirtualClock
from worker.call_behavior import DtmfCollector, DtmfConfig


def collector(**config: object) -> tuple[VirtualClock, DtmfCollector, list[tuple[str, str]]]:
    clock = VirtualClock()
    flushed: list[tuple[str, str]] = []
    c = DtmfCollector(
        clock,
        DtmfConfig(enabled=True, **config),  # type: ignore[arg-type]
        lambda digits, reason: flushed.append((digits, reason)),
    )
    return clock, c, flushed


def test_termination_key_flushes_without_the_key() -> None:
    _, c, flushed = collector()
    for d in "1234#":
        c.add(d)
    assert flushed == [("1234", "termination_key")]
    assert c.pending == ""


def test_digit_limit_flushes() -> None:
    _, c, flushed = collector(digits=3, termination_key=None)
    for d in "12345":
        c.add(d)
    assert flushed == [("123", "digit_limit")]
    assert c.pending == "45"


def test_pause_timeout_flushes() -> None:
    clock, c, flushed = collector(timeout_ms=2500)
    c.add("4")
    clock.set_time(1.0)
    c.add("2")  # resets the pause timer
    while clock.fire_next(3.4):
        pass
    assert flushed == []
    while clock.fire_next(3.5):
        pass
    assert flushed == [("42", "timeout")]


def test_star_can_be_termination_key_and_hash_a_digit() -> None:
    _, c, flushed = collector(termination_key="*")
    for d in "9#*":
        c.add(d)
    assert flushed == [("9#", "termination_key")]


def test_termination_with_empty_buffer_does_nothing() -> None:
    _, c, flushed = collector()
    c.add("#")
    assert flushed == []


def test_invalid_digit_rejected() -> None:
    _, c, _ = collector()
    with pytest.raises(ValueError):
        c.add("A")


def test_digits_during_agent_speech_are_still_collected() -> None:
    """Keypad input does not depend on who is speaking; the runner turns it into a turn."""
    _, c, flushed = collector()
    c.add("7")
    c.add("#")
    assert flushed == [("7", "termination_key")]
