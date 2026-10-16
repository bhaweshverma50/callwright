"""Dynamic variable validation and resolution (FR-005, FR-006, data-model section 10).

Order: value supplied for the call, then the agent's default, then empty. Built-in variables are
set by the platform; a caller value for one is ignored and listed in ``ignored``. A name the
prompt or greeting references with no value and no default renders empty and is listed in
``missing``. The worker renders ``{{name}}`` with the same pattern.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BUILTIN_VARIABLES = (
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
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*\}\}")
MAX_VARIABLES = 50
MAX_VALUE_CHARS = 2000


@dataclass(frozen=True)
class VariableIssue:
    pointer: str
    code: str
    message: str


def validate_supplied(values: Mapping[str, Any]) -> list[VariableIssue]:
    issues: list[VariableIssue] = []
    if len(values) > MAX_VARIABLES:
        issues.append(
            VariableIssue("/dynamic_variables", "out_of_range", f"At most {MAX_VARIABLES} variables.")
        )
    for name, value in values.items():
        pointer = f"/dynamic_variables/{name}"
        if not NAME.match(name):
            issues.append(
                VariableIssue(
                    pointer,
                    "invalid_format",
                    "Names start with a letter or underscore and use letters, digits and underscores.",
                )
            )
        if not isinstance(value, str):
            issues.append(VariableIssue(pointer, "invalid_format", "Values are strings."))
        elif len(value) > MAX_VALUE_CHARS:
            issues.append(
                VariableIssue(pointer, "out_of_range", f"Values are at most {MAX_VALUE_CHARS} characters.")
            )
    return issues


def referenced_names(texts: Iterable[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for text in texts:
        for match in PLACEHOLDER.finditer(text or ""):
            seen.setdefault(match.group(1), None)
    return list(seen)


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
    """Built-ins: the caller is ``from`` on inbound calls and ``to`` on outbound calls."""
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


@dataclass(frozen=True)
class ResolvedVariables:
    values: dict[str, str]
    missing: list[str]
    ignored: list[str]


def resolve(
    config: Mapping[str, Any], supplied: Mapping[str, str], builtins: Mapping[str, str]
) -> ResolvedVariables:
    declared: dict[str, str | None] = {}
    for item in config.get("dynamic_variables") or []:
        if isinstance(item, Mapping) and isinstance(item.get("name"), str):
            default = item.get("default")
            declared[item["name"]] = default if isinstance(default, str) else None
    ignored = sorted(name for name in supplied if name in builtins)
    values: dict[str, str] = {}
    missing: list[str] = []
    for name, default in declared.items():
        if name in builtins:
            continue
        if name in supplied:
            values[name] = supplied[name]
        elif default is not None:
            values[name] = default
        else:
            values[name] = ""
            missing.append(name)
    for name, value in supplied.items():
        if name not in builtins and name not in values:
            values[name] = value
    texts = [config.get("prompt"), config.get("begin_message")]
    for name in referenced_names(t if isinstance(t, str) else None for t in texts):
        if name not in builtins and name not in values:
            values[name] = ""
            missing.append(name)
    values.update(builtins)
    return ResolvedVariables(values=values, missing=missing, ignored=ignored)
