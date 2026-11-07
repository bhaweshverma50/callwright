"""Dynamic variables: built-in names, the name rule, limits and the ``{{name}}`` grammar
(002 FR-008, 003 FR-005, 004 research R6).

Built-ins are set by the API at admission for every call (:func:`builtin_values`; the text runner
and the offline harness use the same function) and may appear in any text but cannot be
declared. :func:`local_now` reads the call's local time back from them. Placeholders tolerate
spaces inside the braces; flow text also reads one level of dotted name for task results
(``{{task_result.email}}``). HTTP tool templates use their own wider grammar
(``http_core.PLACEHOLDER``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timezone
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BUILTIN_VARIABLES: Final[tuple[str, ...]] = (
    "call_id",
    "channel",
    "direction",
    "user_number",
    "agent_number",
    "timezone",
    "current_time",
    "current_date",
    "current_datetime",
)
# Set on a callback call (011): why the agent is calling back.
CALLBACK_NOTE: Final = "callback_note"

_NAME = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
NAME_PATTERN: Final = rf"^{_NAME}$"
NAME = re.compile(NAME_PATTERN)
PLACEHOLDER = re.compile(rf"\{{\{{\s*({_NAME})\s*\}}\}}")
DOTTED_PLACEHOLDER = re.compile(rf"\{{\{{\s*({_NAME}(?:\.{_NAME})?)\s*\}}\}}")

MAX_VARIABLES: Final = 50
MAX_VALUE_CHARS: Final = 2000
MAX_DESCRIPTION_CHARS: Final = 200


def render(text: str, variables: Mapping[str, str]) -> str:
    """Replace ``{{name}}`` placeholders; a name with no value renders empty, never raw."""
    return PLACEHOLDER.sub(lambda m: str(variables.get(m.group(1), "")), text)


def builtin_values(
    *,
    call_id: str,
    channel: str,
    direction: str,
    from_number: str | None,
    to_number: str | None,
    timezone: str | None,
    now: datetime,
) -> dict[str, str]:
    """The built-ins of a call: the caller is ``from`` on inbound calls and ``to`` on outbound
    calls; times are in ``timezone`` (UTC when unknown)."""
    tz_name = timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz_name, tz = "UTC", ZoneInfo("UTC")
    local = now.astimezone(tz)
    inbound = direction == "inbound"
    return {
        "call_id": call_id,
        "channel": channel,
        "direction": direction,
        "user_number": (from_number if inbound else to_number) or "",
        "agent_number": (to_number if inbound else from_number) or "",
        "timezone": tz_name,
        "current_time": local.strftime("%H:%M"),
        "current_date": local.strftime("%Y-%m-%d"),
        "current_datetime": local.isoformat(timespec="minutes"),
    }


def local_now(variables: Mapping[str, Any], now: datetime | None = None) -> datetime:
    """Now in the call's zone, from the ``current_datetime`` built-in (it carries the offset);
    UTC when the call has none."""
    now = now or datetime.now(UTC)
    raw = str(variables.get("current_datetime") or "")
    try:
        offset = datetime.fromisoformat(raw).utcoffset()
    except ValueError:
        offset = None
    return now.astimezone(timezone(offset) if offset is not None else UTC)
