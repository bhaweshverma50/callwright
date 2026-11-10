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
from datetime import datetime, timedelta
from typing import Any

from callwright_contract.protocol import CallbackRequest
from callwright_contract.values import (
    CALLBACK_MAX_IN_MINUTES,
    CALLBACK_MAX_NOTE_CHARS,
    CALLBACK_NOT_A_PHONE_CALL,
    CALLBACK_REFUSALS,
    ToolErrorCode,
    spoken_time,
)
from callwright_contract.variables import local_now

from worker.internal_api import InternalApiClient, InternalApiError
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


def _confirmation(spoken: str) -> str:
    return (
        f"Callback booked for {spoken}. Tell the caller that time, then say goodbye and end the "
        "call."
    )


def _mocked_error(code: ToolErrorCode, message: str) -> ToolResult:
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
    def __init__(self, api: InternalApiClient | None, *, timeout_s: float = TIMEOUT_S) -> None:
        self.api = api
        self.timeout_s = timeout_s

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        if arguments.get("at") is None and arguments.get("in_minutes") is None:
            return ToolResult.error("invalid_arguments", "Pass at or in_minutes.")
        if ctx.simulation:
            return simulated(arguments, ctx.dynamic_variables)
        if not ctx.is_sip:
            return ToolResult.error("channel_unsupported", CALLBACK_NOT_A_PHONE_CALL)
        if self.api is None:
            return ToolResult.error("unavailable", UNAVAILABLE)
        note = str(arguments.get("note") or "")[:CALLBACK_MAX_NOTE_CHARS]
        if arguments.get("in_minutes") is not None:
            body = CallbackRequest(in_minutes=int(arguments["in_minutes"]), note=note)
        else:
            body = CallbackRequest(at=str(arguments["at"])[:40], note=note)
        try:
            status, data = await self.api.schedule_callback(
                ctx.call_id, body, timeout_s=self.timeout_s
            )
        except InternalApiError:
            return ToolResult.error("unavailable", UNAVAILABLE)
        if status in (200, 201) and isinstance(data, dict):
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
        reason = data.get("reason") if status == 422 and isinstance(data, dict) else None
        if reason in CALLBACK_REFUSALS:
            return ToolResult.error(reason, str(data.get("detail") or UNAVAILABLE))
        return ToolResult.error("unavailable", UNAVAILABLE)
