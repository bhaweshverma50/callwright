"""Dashboard period resolution (006 T043, FR-017, data-model ``DashboardPeriod``).

Presets cover whole calendar days in the viewer's timezone ending today (inclusive). A custom
range needs both dates, an end on or after the start and at most 731 days. "All time" starts on
the day of the workspace's first call. The resolved window is ``[start, end)`` in UTC; ranges
over 180 days bucket by ISO week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import ProblemError, field_error, validation_failed

PRESET_DAYS = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}
PERIODS = ("all_time", *PRESET_DAYS, "custom")
MAX_DAYS = 731
WEEKLY_AFTER_DAYS = 180


def zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise validation_failed(
            [field_error("/tz", "invalid_format", "Use an IANA timezone such as Asia/Kolkata.")]
        ) from exc


@dataclass(frozen=True)
class Window:
    start_date: date
    end_date: date  # inclusive
    tz: ZoneInfo

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def bucket(self) -> Literal["day", "week"]:
        return "week" if self.days > WEEKLY_AFTER_DAYS else "day"

    def _midnight(self, d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=self.tz).astimezone(UTC)

    @property
    def start(self) -> datetime:
        return self._midnight(self.start_date)

    @property
    def end(self) -> datetime:
        return self._midnight(self.end_date + timedelta(days=1))

    def prior(self) -> Window:
        return Window(
            self.start_date - timedelta(days=self.days), self.start_date - timedelta(days=1), self.tz
        )

    def as_json(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise validation_failed(
            [field_error(f"/{name}", "invalid_format", "Use a date like 2026-10-01.")]
        ) from exc


def resolve_period(
    period: str | None,
    start_date: str | None,
    end_date: str | None,
    tz: str | None,
    *,
    today: date | None = None,
    first_call_day: date | None = None,
) -> Window:
    tzinfo = zone(tz)
    today = today or datetime.now(tzinfo).date()
    period = period or "last_30_days"
    if period not in PERIODS:
        raise validation_failed(
            [field_error("/period", "not_in_catalog", f"Period is one of {', '.join(PERIODS)}.")]
        )
    if period in PRESET_DAYS:
        return Window(today - timedelta(days=PRESET_DAYS[period] - 1), today, tzinfo)
    if period == "all_time":
        start = min(first_call_day, today) if first_call_day else today
        return Window(start, today, tzinfo)
    first, last = _date(start_date, "start_date"), _date(end_date, "end_date")
    if first is None or last is None:
        raise validation_failed(
            [field_error("/start_date", "required", "Pick a start and an end date for a custom range.")]
        )
    if last < first:
        raise ProblemError(
            422,
            "validation_failed",
            "Request is not valid",
            "End date must be on or after start date.",
            errors=[field_error("/end_date", "out_of_range", "End date must be on or after start date.")],
        )
    window = Window(first, last, tzinfo)
    if window.days > MAX_DAYS:
        raise ProblemError(
            422,
            "validation_failed",
            "Request is not valid",
            f"A custom range can cover at most {MAX_DAYS} days.",
            errors=[
                field_error("/end_date", "out_of_range", f"A custom range can cover at most {MAX_DAYS} days.")
            ],
        )
    return window
