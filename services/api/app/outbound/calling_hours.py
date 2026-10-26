"""Calling-hour windows and the recipient-local-time check (010 T076, FR-036, FR-037, R9).

Windows are per weekday in the recipient's local time: ``{"start": "HH:MM", "end": "HH:MM"}``
(``end`` may be ``24:00``) or ``null`` for no calls that day; they never cross midnight. The
recipient's zone is the request override, else every zone ``phonenumbers`` gives for the
destination. With several zones the call is allowed only when every zone is inside its window,
and an unknown zone blocks. ``next_allowed_at`` is the earliest instant at which the check
passes: the allowed set is an intersection of unions of intervals, so that instant is ``now`` or
the start of some zone's window, and only those candidates are tested.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import phonenumbers
from phonenumbers import timezone as pn_timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbound.models import OutboundCallingHours

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_WINDOW = {"start": "09:00", "end": "21:00"}
DEFAULT_WINDOWS: dict[str, dict[str, str] | None] = {d: dict(DEFAULT_WINDOW) for d in DAYS}
_START = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_END = re.compile(r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")
UNKNOWN_ZONE = "Etc/Unknown"
LOOKAHEAD_DAYS = 8


class InvalidWindow(ValueError):
    def __init__(self, pointer: str, message: str) -> None:
        super().__init__(message)
        self.pointer = pointer


class InvalidTimezone(ValueError):
    pass


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def validate_windows(windows: Any) -> dict[str, dict[str, str] | None]:
    """All seven weekdays, ``HH:MM`` bounds, start before end; raises ``InvalidWindow``."""
    if not isinstance(windows, Mapping):
        raise InvalidWindow("/windows", "Give a window for each weekday.")
    out: dict[str, dict[str, str] | None] = {}
    for day in DAYS:
        if day not in windows:
            raise InvalidWindow(f"/windows/{day}", "Every weekday needs a window or null.")
        value = windows[day]
        if value is None:
            out[day] = None
            continue
        if not isinstance(value, Mapping) or set(value) != {"start", "end"}:
            raise InvalidWindow(f"/windows/{day}", "A window has a start and an end.")
        start, end = value["start"], value["end"]
        if not isinstance(start, str) or not _START.match(start):
            raise InvalidWindow(f"/windows/{day}/start", "Use HH:MM from 00:00 to 23:59.")
        if not isinstance(end, str) or not _END.match(end):
            raise InvalidWindow(f"/windows/{day}/end", "Use HH:MM from 00:01 to 24:00.")
        if _minutes(start) >= _minutes(end):
            raise InvalidWindow(f"/windows/{day}", "The start must be before the end.")
        out[day] = {"start": start, "end": end}
    extra = set(windows) - set(DAYS)
    if extra:
        raise InvalidWindow(f"/windows/{sorted(extra)[0]}", "Unknown weekday.")
    return out


def check_timezone(name: str) -> str:
    if name == UNKNOWN_ZONE or name not in _zones():
        raise InvalidTimezone(f"{name!r} is not an IANA timezone name, for example America/New_York.")
    return name


_ZONE_CACHE: set[str] = set()


def _zones() -> set[str]:
    if not _ZONE_CACHE:
        _ZONE_CACHE.update(available_timezones())
    return _ZONE_CACHE


def recipient_zones(to_number: str, override: str | None) -> tuple[list[str], str]:
    """``(zones, source)`` with source ``override``, ``number_region`` or ``unknown``."""
    if override:
        return [check_timezone(override)], "override"
    try:
        parsed = phonenumbers.parse(to_number, None)
    except phonenumbers.NumberParseException:
        return [], "unknown"
    zones = []
    for zone in pn_timezone.time_zones_for_number(parsed):
        if zone == UNKNOWN_ZONE:
            continue
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        zones.append(zone)
    return (zones, "number_region") if zones else ([], "unknown")


@dataclass(frozen=True)
class Evaluation:
    allowed: bool
    zones: list[str]
    source: str
    local_time: datetime | None
    next_allowed_at: datetime | None


def _inside(windows: Mapping[str, Any], zone: ZoneInfo, instant: datetime) -> bool:
    local = instant.astimezone(zone)
    window = windows.get(DAYS[local.weekday()])
    if not window:
        return False
    minute = local.hour * 60 + local.minute
    return _minutes(window["start"]) <= minute < _minutes(window["end"])


def _window_starts(windows: Mapping[str, Any], zone: ZoneInfo, now: datetime) -> list[datetime]:
    today: date = now.astimezone(zone).date()
    out = []
    for offset in range(LOOKAHEAD_DAYS):
        day = today + timedelta(days=offset)
        window = windows.get(DAYS[day.weekday()])
        if not window:
            continue
        start = _minutes(window["start"])
        local = datetime.combine(day, time(start // 60, start % 60), tzinfo=zone)
        out.append(local.astimezone(UTC))
    return out


def evaluate(
    windows: Mapping[str, Any], zones: Sequence[str], source: str, now: datetime | None = None
) -> Evaluation:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if not zones:
        return Evaluation(False, [], "unknown", None, None)
    infos = [ZoneInfo(z) for z in zones]
    local_time = now.astimezone(infos[0]).replace(tzinfo=None, microsecond=0)
    if all(_inside(windows, zone, now) for zone in infos):
        return Evaluation(True, list(zones), source, local_time, None)
    candidates = sorted({t for zone in infos for t in _window_starts(windows, zone, now) if t > now})
    next_at = next((t for t in candidates if all(_inside(windows, zone, t) for zone in infos)), None)
    return Evaluation(False, list(zones), source, local_time, next_at)


async def get_windows(session: AsyncSession, workspace_id: str) -> OutboundCallingHours | None:
    return await session.get(OutboundCallingHours, workspace_id)


def view(row: OutboundCallingHours | None) -> dict[str, Any]:
    windows = row.windows if row is not None else DEFAULT_WINDOWS
    return {
        "windows": windows,
        "is_default": windows == DEFAULT_WINDOWS,
        "updated_by_user_id": row.updated_by_user_id if row is not None else None,
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


async def put_windows(
    session: AsyncSession, workspace_id: str, user_id: str | None, windows: Mapping[str, Any]
) -> OutboundCallingHours:
    clean = validate_windows(windows)
    row = await session.get(OutboundCallingHours, workspace_id, with_for_update=True)
    now = datetime.now(UTC)
    if row is None:
        row = OutboundCallingHours(
            workspace_id=workspace_id, windows=clean, updated_by_user_id=user_id, updated_at=now
        )
        session.add(row)
    else:
        row.windows = clean
        row.updated_by_user_id = user_id
        row.updated_at = now
    await session.flush()
    return row
