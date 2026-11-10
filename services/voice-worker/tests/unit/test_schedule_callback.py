"""Built-in schedule_callback tool (011): schema, the API booking, refusals the agent relays,
non-phone calls refused without a request, and simulations answered locally."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from callwright_contract.variables import local_now

from tests.unit.tool_support import make
from worker.tools.registry import BUILTIN_SCHEDULE_CALLBACK, function_schema
from worker.tools.schedule_callback import simulated


def recording(seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    return handler


def test_schema_offers_at_in_minutes_and_note() -> None:
    schema = function_schema(BUILTIN_SCHEDULE_CALLBACK)
    assert schema["name"] == "schedule_callback"
    assert set(schema["parameters"]["properties"]) == {"at", "in_minutes", "note"}
    assert schema["parameters"]["required"] == ["note"]


async def test_books_through_the_api_and_returns_the_time_to_say() -> None:
    seen: list[httpx.Request] = []

    def api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            201,
            json={
                "scheduled": True,
                "mocked": False,
                "callback_id": "cbk_01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "scheduled_at": "2026-11-04T11:30:00Z",
                "timezone": "Asia/Kolkata",
                "local_time": "2026-11-04T17:00",
                "spoken_time": "tomorrow, Wednesday 4 November, at 5:00 pm",
                "rescheduled": False,
            },
        )

    h = make([], api_handler=api)
    payload = json.loads(
        await h.tools.dispatch(
            "schedule_callback", {"at": "2026-11-04T17:00", "note": "Finish rebooking"}
        )
    )
    assert payload["scheduled"] and "5:00 pm" in payload["message"]
    assert str(seen[0].url) == "http://api.test/v1/internal/calls/call_test/callbacks"
    assert json.loads(seen[0].content) == {"note": "Finish rebooking", "at": "2026-11-04T17:00"}
    assert seen[0].headers["authorization"] == "Bearer svc"
    event = h.events()[0]
    assert event["tool_type"] == "schedule_callback" and not event["is_error"]
    assert event["callback_id"] == "cbk_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_refusals_are_relayed() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "code": "callback_not_possible",
                "reason": "outside_calling_hours",
                "detail": "The earliest allowed time after it is tomorrow at 9:00 am.",
            },
        )

    h = make([], api_handler=api)
    payload = json.loads(
        await h.tools.dispatch("schedule_callback", {"in_minutes": 600, "note": "x"})
    )
    assert payload == {
        "error": "outside_calling_hours",
        "message": "The earliest allowed time after it is tomorrow at 9:00 am.",
    }

    down = make([], api_handler=lambda r: httpx.Response(503, json={}))
    failed = json.loads(
        await down.tools.dispatch("schedule_callback", {"in_minutes": 5, "note": ""})
    )
    assert failed["error"] == "unavailable" and "do not promise" in failed["message"]

    neither = json.loads(await down.tools.dispatch("schedule_callback", {"note": "x"}))
    assert neither["error"] == "invalid_arguments"


async def test_browser_calls_are_refused_without_a_request() -> None:
    seen: list[httpx.Request] = []
    h = make([], channel="web", api_handler=recording(seen))
    payload = json.loads(
        await h.tools.dispatch("schedule_callback", {"in_minutes": 30, "note": "x"})
    )
    assert payload["error"] == "channel_unsupported" and "phone calls" in payload["message"]
    assert seen == []


async def test_simulations_answer_locally_and_never_call_the_api() -> None:
    seen: list[httpx.Request] = []
    h = make([], simulation=True, api_handler=recording(seen))
    payload = json.loads(
        await h.tools.dispatch("schedule_callback", {"in_minutes": 60, "note": "x"})
    )
    assert payload["scheduled"] and seen == []
    assert h.events()[0]["mocked"] is True


def test_simulated_reads_local_times_in_the_call_zone() -> None:
    variables: dict[str, Any] = {"current_datetime": "2026-11-03T14:05+05:30"}
    now = local_now(variables, datetime(2026, 11, 3, 8, 35, tzinfo=UTC))
    assert now.isoformat() == "2026-11-03T14:05:00+05:30"
    result = simulated({"at": "2099-01-01T09:00", "note": ""}, variables)
    assert not result.is_error and result.mocked and "9:00 am" in result.llm_payload
    past = simulated({"at": "2001-01-01T09:00"}, variables)
    assert past.is_error and past.error_code == "invalid_time"
