"""Money test (003 T026, FR-031): billable time is connected to ended, rounded up to the second."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.calls.models import billable_seconds
from app.pricing import engine

T0 = datetime(2026, 10, 16, 10, 0, 0, tzinfo=UTC)


def test_rounds_up_to_whole_seconds() -> None:
    assert billable_seconds(T0, T0 + timedelta(seconds=4.2)) == 5
    assert billable_seconds(T0, T0 + timedelta(seconds=5)) == 5
    assert billable_seconds(T0, T0 + timedelta(milliseconds=5001)) == 6
    assert billable_seconds(T0, T0 + timedelta(milliseconds=1)) == 1


def test_ringing_and_queue_time_are_excluded() -> None:
    created = T0 - timedelta(seconds=20)  # queued and ringing before connection
    assert created < T0
    assert billable_seconds(T0, T0 + timedelta(seconds=30)) == 30


def test_never_connected_bills_zero() -> None:
    assert billable_seconds(None, T0) == 0
    assert billable_seconds(T0, None) == 0
    assert billable_seconds(T0, T0) == 0
    assert billable_seconds(T0, T0 - timedelta(seconds=1)) == 0


def test_matches_the_pricing_engine_rounding() -> None:
    for ms in (1, 999, 1000, 4200, 59_999, 61_001):
        assert billable_seconds(T0, T0 + timedelta(milliseconds=ms)) == engine.billed_seconds(ms)
