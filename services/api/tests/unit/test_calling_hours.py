"""Calling-hour evaluation (010 T071, FR-036, FR-037)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.outbound.calling_hours import (
    DEFAULT_WINDOWS,
    InvalidTimezone,
    InvalidWindow,
    evaluate,
    recipient_zones,
    validate_windows,
)

LA = "+14155550199"  # America/Los_Angeles
NY = "+12125550100"  # America/New_York


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def windows(**days: Any) -> dict[str, Any]:
    out: dict[str, Any] = dict(DEFAULT_WINDOWS)
    out.update(days)
    return out


def check(to: str, now: str, w: dict[str, Any] | None = None, override: str | None = None) -> Any:
    zones, source = recipient_zones(to, override)
    return evaluate(w or DEFAULT_WINDOWS, zones, source, at(now))


def test_default_window_in_recipient_local_time() -> None:
    # 2026-10-16 is a Friday. 16:30 UTC is 09:30 in Los Angeles (PDT, UTC-7).
    ok = check(LA, "2026-10-16T16:30:00+00:00")
    assert ok.allowed and ok.zones == ["America/Los_Angeles"] and ok.source == "number_region"
    early = check(LA, "2026-10-16T15:59:00+00:00")  # 08:59 local
    assert not early.allowed
    assert early.local_time == datetime(2026, 10, 16, 8, 59)
    assert early.next_allowed_at == at("2026-10-16T16:00:00+00:00")
    late = check(LA, "2026-10-17T04:30:00+00:00")  # Friday 21:30 local
    assert not late.allowed and late.next_allowed_at == at("2026-10-17T16:00:00+00:00")


def test_end_is_exclusive_and_24_00_means_end_of_day() -> None:
    w = windows(fri={"start": "00:00", "end": "24:00"})
    assert check(LA, "2026-10-17T06:59:00+00:00", w).allowed  # Friday 23:59 local
    assert not check(LA, "2026-10-17T07:00:00+00:00", windows(sat=None)).allowed  # Saturday 00:00
    exact_end = check(LA, "2026-10-17T04:00:00+00:00")  # Friday 21:00 local, end is exclusive
    assert not exact_end.allowed


def test_per_weekday_windows_and_null_day_use_recipient_weekday() -> None:
    # Saturday 10:00 in Los Angeles is still Saturday there, while it is Saturday 17:00 UTC.
    w = windows(sat=None)
    blocked = check(LA, "2026-10-17T17:00:00+00:00", w)
    assert not blocked.allowed
    assert blocked.next_allowed_at == at("2026-10-18T16:00:00+00:00")  # Sunday 09:00 local
    # Monday 01:00 UTC is still Sunday 18:00 in Los Angeles: Sunday's window applies.
    sunday = windows(sun={"start": "17:00", "end": "19:00"}, mon=None)
    assert check(LA, "2026-10-19T01:00:00+00:00", sunday).allowed


def test_no_window_any_day_has_no_next_time() -> None:
    w = dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
    result = check(LA, "2026-10-16T18:00:00+00:00", w)
    assert not result.allowed and result.next_allowed_at is None


def test_dst_day_uses_local_wall_clock() -> None:
    # US DST ends 2026-11-01. 09:00 PST is 17:00 UTC (the day before it was 16:00 UTC).
    assert not check(LA, "2026-11-01T16:30:00+00:00").allowed
    assert check(LA, "2026-11-01T17:00:00+00:00").allowed
    before = check(LA, "2026-11-01T15:00:00+00:00")
    assert before.next_allowed_at == at("2026-11-01T17:00:00+00:00")


def test_override_takes_precedence() -> None:
    # 16:30 UTC: 09:30 in Los Angeles but 12:30 in New York; 03:00 UTC: 20:00 LA, 23:00 NY.
    result = check(LA, "2026-10-17T03:00:00+00:00", override="America/New_York")
    assert not result.allowed and result.source == "override" and result.zones == ["America/New_York"]
    assert check(NY, "2026-10-17T03:00:00+00:00", override="America/Los_Angeles").allowed


def test_invalid_override_is_rejected() -> None:
    with pytest.raises(InvalidTimezone):
        recipient_zones(LA, "Mars/Olympus_Mons")
    with pytest.raises(InvalidTimezone):
        recipient_zones(LA, "Etc/Unknown")


def test_multi_zone_number_needs_every_zone() -> None:
    zones, source = recipient_zones("+61412345678", None)  # Australian mobile: Perth to Sydney
    assert source == "number_region" and len(zones) > 1
    # 01:30 UTC: 12:30 in Sydney (AEDT) but 09:30 in Perth; Lord Howe and Christmas Island too.
    early = evaluate(DEFAULT_WINDOWS, zones, source, at("2026-10-16T00:30:00+00:00"))
    assert not early.allowed  # 08:30 in Perth
    assert early.next_allowed_at is not None
    assert evaluate(DEFAULT_WINDOWS, zones, source, early.next_allowed_at).allowed
    # 08:00 UTC: 16:00 Perth, 19:00 Sydney, 19:30 Lord Howe: every zone inside.
    assert evaluate(DEFAULT_WINDOWS, zones, source, at("2026-10-16T08:00:00+00:00")).allowed


def test_unknown_zone_blocks() -> None:
    zones, source = recipient_zones("+882345678901", None)
    assert zones == [] and source == "unknown"
    result = evaluate(DEFAULT_WINDOWS, zones, source, at("2026-10-16T18:00:00+00:00"))
    assert not result.allowed and result.next_allowed_at is None and result.local_time is None


@pytest.mark.parametrize(
    ("value", "pointer"),
    [
        ({"mon": None}, "/windows/tue"),
        (windows(mon={"start": "10:00", "end": "09:00"}), "/windows/mon"),
        (windows(mon={"start": "10:00", "end": "10:00"}), "/windows/mon"),
        (windows(tue={"start": "24:00", "end": "24:00"}), "/windows/tue/start"),
        (windows(wed={"start": "9:00", "end": "17:00"}), "/windows/wed/start"),
        (windows(thu={"start": "09:00", "end": "24:01"}), "/windows/thu/end"),
        (windows(fri={"start": "09:00"}), "/windows/fri"),
    ],
)
def test_invalid_windows(value: dict[str, Any], pointer: str) -> None:
    with pytest.raises(InvalidWindow) as exc:
        validate_windows(value)
    assert exc.value.pointer == pointer


def test_valid_windows_roundtrip() -> None:
    w = windows(sat=None, sun={"start": "00:00", "end": "24:00"})
    assert validate_windows(w) == w
