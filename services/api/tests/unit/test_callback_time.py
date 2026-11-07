"""Callback times (011): how a booked time is read."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from callwright_contract.protocol import CallbackRequest

from app.callbacks.service import resolve_time
from app.calls.variables import number_timezone
from app.core.errors import ProblemError

KOLKATA = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 3, 14, 5, tzinfo=KOLKATA)  # a Tuesday


def test_resolve_time_reads_local_offset_and_relative() -> None:
    now = NOW.astimezone(UTC)
    local = resolve_time(CallbackRequest(at="2026-11-04T17:00"), "Asia/Kolkata", now)
    assert local == datetime(2026, 11, 4, 11, 30, tzinfo=UTC)
    offset = resolve_time(CallbackRequest(at="2026-11-04T17:00:00Z"), "Asia/Kolkata", now)
    assert offset == datetime(2026, 11, 4, 17, 0, tzinfo=UTC)
    relative = resolve_time(CallbackRequest(in_minutes=60), "Asia/Kolkata", now)
    assert relative == datetime(2026, 11, 3, 9, 35, tzinfo=UTC)
    with pytest.raises(ProblemError) as caught:
        resolve_time(CallbackRequest(at="tomorrow at 5"), "Asia/Kolkata", now)
    assert caught.value.extra["reason"] == "invalid_time"


def test_book_request_needs_exactly_one_time() -> None:
    with pytest.raises(ValueError):
        CallbackRequest(note="x")
    with pytest.raises(ValueError):
        CallbackRequest(at="2026-11-04T17:00", in_minutes=5)


def test_number_timezone() -> None:
    assert number_timezone("+919000000001") == "Asia/Calcutta"
    assert number_timezone("+14155550123") == "America/Los_Angeles"
    assert number_timezone("anonymous") is None
    assert number_timezone(None) is None
