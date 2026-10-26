"""Tool registry (005 T013): function shapes per type, argument checks, timed non-blocking
events, kb_search injection and the per-node switch for 004."""

from __future__ import annotations

import json
from typing import Any

from tests.unit.tool_support import http_spec, make, tool
from worker.tools.base import ToolSpecView
from worker.tools.registry import function_schema, validate_arguments


def schema_of(raw: dict[str, Any]) -> dict[str, Any]:
    return function_schema(ToolSpecView.from_snapshot(raw))


def test_function_shapes_per_type() -> None:
    assert schema_of(tool("end_call", "end_call"))["parameters"]["properties"] == {}
    static = schema_of(
        tool("transfer_call", "transfer", {"routing_type": "static", "number": "+14155550100"})
    )
    assert static["parameters"]["properties"] == {}
    dynamic = schema_of(
        tool(
            "transfer_call",
            "route",
            {
                "routing_type": "dynamic",
                "routing_instructions": "Sales or support",
                "allowed_numbers": ["+14155550100"],
            },
        )
    )
    assert dynamic["parameters"]["required"] == ["destination"]
    assert dynamic["parameters"]["properties"]["destination"]["enum"] == ["+14155550100"]
    assert "Sales or support" in dynamic["description"]
    digits = schema_of(tool("press_digit", "press"))
    assert digits["parameters"]["properties"]["digits"]["pattern"] == r"^[0-9*#]{1,20}$"
    assert schema_of(http_spec())["parameters"]["required"] == ["date"]


def test_argument_validation() -> None:
    schema = {
        "type": "object",
        "properties": {
            "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
            "n": {"type": "integer"},
        },
        "required": ["date"],
    }
    assert validate_arguments(schema, {"date": "2026-10-20", "n": 2}) is None
    assert validate_arguments(schema, {}) == "date is required"
    assert validate_arguments(schema, {"date": "tomorrow"}) == "date has the wrong format"
    assert validate_arguments(schema, {"date": "2026-10-20", "n": True}) == "n must be integer"


async def test_invalid_arguments_go_back_to_the_llm_without_running() -> None:
    h = make([http_spec()])
    payload = await h.tools.dispatch("check_availability", {})
    assert json.loads(payload)["error"] == "invalid_arguments"
    assert h.requests == []
    [event] = h.events()
    assert event["is_error"] and event["error_code"] == "invalid_arguments"


async def test_events_carry_timing_and_type() -> None:
    h = make([http_spec()])
    await h.tools.dispatch("check_availability", {"date": "2026-10-20"})
    [event] = h.events()
    assert event["name"] == "check_availability" and event["tool_type"] == "http"
    assert (
        event["tool_id"] == "tool_check_availability" and event["ref"] == "tool_check_availability"
    )
    assert event["duration_ms"] >= 0 and 0 <= event["dispatch_overhead_ms"] <= event["duration_ms"]
    assert event["http_status"] == 200 and event["mocked"] is False
    assert event["arguments"] == {"date": "2026-10-20"}


async def test_reporting_failure_does_not_break_dispatch() -> None:
    h = make([tool("end_call", "end_call")])

    def broken(_: Any) -> None:
        raise RuntimeError("recorder down")

    h.tools.control.report_tool = broken  # type: ignore[method-assign]
    assert json.loads(await h.tools.dispatch("end_call", {})) == {"ended": True}


def test_kb_search_is_injected_and_switchable() -> None:
    h = make(
        [tool("end_call", "end_call")],
        knowledge=[{"kb_id": "kb_1", "name": "Clinic FAQ", "description": "hours"}],
    )
    names = [s["name"] for s in h.tools.schemas()]
    assert names == ["end_call", "kb_search"]
    kb = h.tools.schemas()[-1]
    assert "Clinic FAQ (hours)" in kb["description"]
    assert [s["name"] for s in h.tools.schemas(kb_search_enabled=False)] == ["end_call"]


def test_function_tools_build_livekit_raw_tools() -> None:
    h = make([tool("end_call", "end_call"), http_spec()])
    built = h.tools.function_tools()
    assert [t.info.name for t in built] == ["end_call", "check_availability"]


def test_fillers_cover_lookup_tools_only() -> None:
    quiet = http_spec("quiet_lookup", speak_during_execution=False)
    h = make(
        [tool("end_call", "end_call"), http_spec(), quiet, tool("press_digit", "press")],
        knowledge=[{"kb_id": "kb_1", "name": "FAQ", "description": ""}],
    )
    assert h.tools.fillers.texts == {
        "check_availability": "One moment while I check that.",
        "kb_search": "One moment, let me check that.",
    }
