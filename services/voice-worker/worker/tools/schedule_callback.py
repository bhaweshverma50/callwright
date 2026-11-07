"""Built-in ``schedule_callback`` tool (011).

Books a callback for the person on the call through ``POST /v1/internal/calls/{id}/callbacks``:
the API picks the number to call and the number to call from, checks the do-not-call list and
calling hours at the booked time, and answers with the time to say back (``spoken_time``) or a
refusal sentence the agent relays. Calls that are not phone calls are refused here without a
request. Simulations (008) never reach the API: the answer is computed locally, marked mocked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
from callwright_contract.values import (
    CALLBACK_MAX_IN_MINUTES,
    CALLBACK_MAX_NOTE_CHARS,
    CALLBACK_NOT_A_PHONE_CALL,
    CHANNEL_UNSUPPORTED,
    spoken_time,
)

from worker.tools.base import ToolContext, ToolResult, ToolSpecView

TOOL_TYPE = "schedule_callback"
TIMEOUT_S = 5.0
UNAVAILABLE = (
    "The callback could not be booked right now. Tell the caller you could not book it and do "
    "not promise a callback."
)

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "at": {
            "type": "string",
            "description": (
                "The local date and time the caller agreed to, ISO 8601 without offset, for "
                "example 2026-11-04T17:00. Work it out from the current local date and time in "
                "your instructions."
            ),
        },
        "in_minutes": {
            "type": "integer",
            "minimum": 1,
            "maximum": CALLBACK_MAX_IN_MINUTES,
            "description": (
                "Instead of at, for relative times: minutes from now (60 for 'in an hour')."
            ),
        },
        "note": {
            "type": "string",
            "maxLength": CALLBACK_MAX_NOTE_CHARS,
            "description": "One sentence: why to call back and what to continue on the callback.",
        },
    },
    "required": ["note"],
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


def _confirmation(spoken: str) -> str:
    return (
        f"Callback booked for {spoken}. Tell the caller that time, then say goodbye and end the "
        "call."
    )


def _mocked_error(code: str, message: str) -> ToolResult:
    result = ToolResult.error(code, message)
    result.mocked = True
    return result


def simulated(arguments: Mapping[str, Any], variables: Mapping[str, Any]) -> ToolResult:
    now = local_now(variables)
    if arguments.get("in_minutes") is not None:
        at = now + timedelta(minutes=int(arguments["in_minutes"]))
    else:
        try:
            at = datetime.fromisoformat(str(arguments.get("at") or ""))
        except ValueError:
            return _mocked_error("invalid_time", "That time could not be read.")
        at = at.replace(tzinfo=now.tzinfo) if at.tzinfo is None else at.astimezone(now.tzinfo)
    if at <= now:
        return _mocked_error("invalid_time", "That time has already passed.")
    spoken = spoken_time(at, now)
    payload = json.dumps(
        {"scheduled": True, "spoken_time": spoken, "message": _confirmation(spoken)},
        separators=(",", ":"),
    )
    return ToolResult(llm_payload=payload, output=payload, mocked=True)


class ScheduleCallbackExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient | None,
        base_url: str,
        service_token: str,
        *,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {service_token}"}
        self.timeout_s = timeout_s

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        if arguments.get("at") is None and arguments.get("in_minutes") is None:
            return ToolResult.error("invalid_arguments", "Pass at or in_minutes.")
        if ctx.simulation:
            return simulated(arguments, ctx.dynamic_variables)
        if not ctx.is_sip:
            return ToolResult.error(CHANNEL_UNSUPPORTED, CALLBACK_NOT_A_PHONE_CALL)
        if self.client is None:
            return ToolResult.error("unavailable", UNAVAILABLE)
        body: dict[str, Any] = {"note": str(arguments.get("note") or "")[:CALLBACK_MAX_NOTE_CHARS]}
        if arguments.get("in_minutes") is not None:
            body["in_minutes"] = int(arguments["in_minutes"])
        else:
            body["at"] = str(arguments["at"])[:40]
        url = f"{self.base_url}/calls/{ctx.call_id}/callbacks"
        try:
            response = await self.client.post(
                url, json=body, headers=self.headers, timeout=self.timeout_s
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return ToolResult.error("unavailable", UNAVAILABLE)
        if response.status_code in (200, 201) and isinstance(data, dict):
            spoken = str(data.get("spoken_time") or data.get("local_time") or "")
            payload = json.dumps(
                {
                    "scheduled": True,
                    "spoken_time": spoken,
                    "timezone": data.get("timezone"),
                    "message": _confirmation(spoken),
                },
                separators=(",", ":"),
            )
            return ToolResult(
                llm_payload=payload,
                output=payload,
                mocked=bool(data.get("mocked")),
                extra={"callback_id": data.get("callback_id")},
            )
        if response.status_code == 422 and isinstance(data, dict) and data.get("reason"):
            return ToolResult.error(str(data["reason"]), str(data.get("detail") or UNAVAILABLE))
        return ToolResult.error("unavailable", UNAVAILABLE)
