"""Dashboard period resolution (006 T040, FR-017)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.errors import ProblemError
from app.dashboard.periods import resolve_period

TODAY = date(2026, 10, 16)


def test_last_7_days_includes_today() -> None:
    w = resolve_period("last_7_days", None, None, "UTC", today=TODAY)
    assert (w.start_date, w.end_date, w.days, w.bucket) == (date(2026, 10, 10), date(2026, 10, 16), 7, "day")
    assert w.start == datetime(2026, 10, 10, tzinfo=UTC) and w.end == datetime(2026, 10, 17, tzinfo=UTC)


@pytest.mark.parametrize(("period", "days"), [("last_30_days", 30), ("last_90_days", 90)])
def test_presets(period: str, days: int) -> None:
    assert resolve_period(period, None, None, "UTC", today=TODAY).days == days


def test_default_is_last_30_days() -> None:
    assert resolve_period(None, None, None, "UTC", today=TODAY).days == 30


def test_custom_end_is_inclusive() -> None:
    w = resolve_period("custom", "2026-10-01", "2026-10-03", "UTC", today=TODAY)
    assert w.days == 3 and w.end == datetime(2026, 10, 4, tzinfo=UTC)


def test_custom_end_before_start() -> None:
    with pytest.raises(ProblemError) as exc:
        resolve_period("custom", "2026-10-10", "2026-10-01", "UTC", today=TODAY)
    assert exc.value.status == 422 and exc.value.detail == "End date must be on or after start date."


def test_custom_needs_both_dates() -> None:
    with pytest.raises(ProblemError):
        resolve_period("custom", "2026-10-10", None, "UTC", today=TODAY)


def test_custom_cap_731_days() -> None:
    assert resolve_period("custom", "2024-10-16", "2026-10-16", "UTC", today=TODAY).days == 731
    with pytest.raises(ProblemError):
        resolve_period("custom", "2024-10-15", "2026-10-16", "UTC", today=TODAY)


def test_kolkata_day_boundary() -> None:
    w = resolve_period("last_7_days", None, None, "Asia/Kolkata", today=TODAY)
    assert w.start == datetime(2026, 10, 9, 18, 30, tzinfo=UTC)


def test_all_time_starts_at_first_call_and_buckets_weekly_past_180_days() -> None:
    w = resolve_period("all_time", None, None, "UTC", today=TODAY, first_call_day=date(2026, 1, 5))
    assert w.start_date == date(2026, 1, 5) and w.bucket == "week"
    empty = resolve_period("all_time", None, None, "UTC", today=TODAY, first_call_day=None)
    assert empty.days == 1


def test_prior_window_has_equal_length() -> None:
    w = resolve_period("last_7_days", None, None, "UTC", today=TODAY)
    prior = w.prior()
    assert prior.end == w.start and prior.days == 7 and prior.start_date == date(2026, 10, 3)


def test_unknown_period_and_timezone() -> None:
    with pytest.raises(ProblemError):
        resolve_period("last_year", None, None, "UTC", today=TODAY)
    with pytest.raises(ProblemError):
        resolve_period("last_7_days", None, None, "Nowhere/Land", today=TODAY)


def test_legacy_zone_alias_resolves() -> None:
    """Browsers in India report Asia/Calcutta; slim Linux images only ship Asia/Kolkata, so the
    tzdata package must supply the alias."""
    from app.dashboard.periods import zone

    assert zone("Asia/Calcutta").utcoffset(datetime(2026, 1, 1)) == zone("Asia/Kolkata").utcoffset(
        datetime(2026, 1, 1)
    )
