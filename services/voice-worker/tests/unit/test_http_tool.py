"""HTTP tool on calls (005 T035, T039): shared vectors, timeout without retry, the waiting line
after 400 ms only, address guard and mapped variables written to the call store."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.unit.tool_support import http_spec, make
from worker.tools import http_core

HERE = Path(__file__).resolve().parent
VECTORS: dict[str, Any] = json.loads((HERE / "fixtures" / "http_exec_vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS["requests"], ids=lambda c: c["name"])
def test_request_vectors(case: dict[str, Any]) -> None:
    prepared = http_core.prepare_request(
        case["spec"],
        case["arguments"],
        case.get("dynamic"),
        case.get("mapped"),
        case.get("secrets"),
    )
    expect = case["expect"]
    assert (prepared.method, prepared.url, prepared.body) == (
        expect["method"],
        expect["url"],
        expect["body"],
    )
    assert prepared.headers == expect["headers"]
    assert prepared.missing_variables == expect["missing"]


@pytest.mark.parametrize("case", VECTORS["mappings"], ids=lambda c: c["name"])
def test_mapping_vectors(case: dict[str, Any]) -> None:
    assert http_core.apply_mappings(case["body"], case["mappings"]) == (
        case["expect"]["mapped"],
        case["expect"]["missing"],
    )


@pytest.mark.parametrize("case", VECTORS["payloads"], ids=lambda c: c["name"])
def test_payload_vectors(case: dict[str, Any]) -> None:
    if "body_repeat" in case:
        payload = http_core.success_payload(
            case["body_repeat"]["text"] * case["body_repeat"]["times"]
        )
        assert len(payload) == case["expect_length"] and payload.endswith(case["expect_suffix"])
    else:
        assert http_core.success_payload(case["body"]) == case["expect"]


def slots(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": {"slots": [{"time": "10:00"}]}})


async def test_mapped_variables_feed_later_tools() -> None:
    first = http_spec(
        response_mappings=[{"variable_name": "next_slot", "json_path": "data.slots[0].time"}]
    )
    second = http_spec(
        "book",
        body_template={"slot": "{{next_slot}}"},
        parameters={"type": "object", "properties": {}},
    )
    h = make([first, second], handler=slots)
    payload = await h.tools.dispatch("check_availability", {"date": "2026-10-20"})
    assert json.loads(payload) == {"data": {"slots": [{"time": "10:00"}]}}
    assert h.tools.ctx.mapped_variables == {"next_slot": "10:00"}
    await h.tools.dispatch("book", {})
    assert json.loads(h.requests[-1].content) == {"slot": "10:00"}
    assert h.events()[0]["mapped_variables"] == {"next_slot": "10:00"}


async def test_secret_headers_and_scrubbing() -> None:
    spec = http_spec(headers=[{"name": "Authorization", "secret": True, "secret_ref": "ref-1"}])

    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"echo": request.headers["authorization"]})

    h = make([spec], handler=echo, secrets={"ref-1": "Bearer sk-12345678"})
    payload = await h.tools.dispatch("check_availability", {"date": "d"})
    assert h.requests[0].headers["authorization"] == "Bearer sk-12345678"
    assert "sk-12345678" not in payload
    assert "sk-12345678" not in json.dumps(h.events())


async def test_missing_secret_is_reported() -> None:
    spec = http_spec(headers=[{"name": "Authorization", "secret": True, "secret_ref": "gone"}])
    h = make([spec])
    payload = json.loads(await h.tools.dispatch("check_availability", {"date": "d"}))
    assert payload["error"] == "secret_unavailable" and h.requests == []


async def test_timeout_without_retry() -> None:
    calls = 0

    def slow(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    h = make([http_spec()], handler=slow)
    payload = json.loads(await h.tools.dispatch("check_availability", {"date": "d"}))
    assert payload["error"] == "timeout" and calls == 1


async def test_upstream_error_and_blocked_address() -> None:
    h = make([http_spec()], handler=lambda r: httpx.Response(500, text="boom"))
    payload = json.loads(await h.tools.dispatch("check_availability", {"date": "d"}))
    assert payload["error"] == "http_status" and payload["message"].endswith("500.")
    blocked = make([http_spec(url="https://10.0.0.8/x")])
    result = json.loads(await blocked.tools.dispatch("check_availability", {"date": "d"}))
    assert result["error"] == "blocked_address" and blocked.requests == []


async def _slow_handler(delay: float) -> Any:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay)
        return httpx.Response(200, json={"ok": True})

    return handler


async def test_waiting_line_only_after_400_ms_and_once() -> None:
    fast = make([http_spec()], handler=await _slow_handler(0.05))
    await fast.tools.dispatch("check_availability", {"date": "d"})
    assert fast.backend.said == [] and fast.events()[0]["spoke_execution_message"] is False

    slow = make([http_spec()], handler=await _slow_handler(0.6))
    await slow.tools.dispatch("check_availability", {"date": "d"})
    assert slow.backend.said == ["One moment while I check that."]
    assert slow.events()[0]["spoke_execution_message"] is True


async def test_no_waiting_line_when_the_reply_already_spoke() -> None:
    h = make([http_spec()], handler=await _slow_handler(0.6))
    h.tools.fillers.reply_spoke = True
    await h.tools.dispatch("check_availability", {"date": "d"})
    assert h.backend.said == []


async def test_waiting_line_off() -> None:
    h = make([http_spec(speak_during_execution=False)], handler=await _slow_handler(0.6))
    await h.tools.dispatch("check_availability", {"date": "d"})
    assert h.backend.said == []
