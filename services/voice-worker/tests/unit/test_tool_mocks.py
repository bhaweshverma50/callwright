"""Simulation mode (005 T083, T100): canned HTTP responses without network, fixed outcomes for
transfer, press digit and end call, and kb_search running for real."""

from __future__ import annotations

import json

import httpx

from tests.unit.tool_support import http_spec, make, tool


async def test_http_returns_mock_without_network_and_maps() -> None:
    spec = http_spec(response_mappings=[{"variable_name": "next_slot", "json_path": "slots[0]"}])
    spec["mock_response"] = '{"slots": ["09:30"]}'
    h = make([spec], simulation=True)
    payload = await h.tools.dispatch("check_availability", {"date": "d"})
    assert json.loads(payload) == {"slots": ["09:30"]} and h.requests == []
    assert h.tools.ctx.mapped_variables == {"next_slot": "09:30"}
    assert h.events()[0]["mocked"] is True


async def test_empty_mock_reports_no_mock_response() -> None:
    h = make([http_spec()], simulation=True)
    payload = json.loads(await h.tools.dispatch("check_availability", {"date": "d"}))
    assert payload["error"] == "no_mock_response" and h.requests == []
    assert h.events()[0]["error_code"] == "no_mock_response" and h.events()[0]["mocked"] is True


async def test_transfer_and_press_digit_fixed_outcomes() -> None:
    transfer = tool(
        "transfer_call", "transfer", {"routing_type": "static", "number": "+14155550100"}
    )
    h = make([transfer, tool("press_digit", "press")], channel="web", simulation=True)
    assert json.loads(await h.tools.dispatch("press", {"digits": "3"})) == {"sent": "3"}
    assert h.backend.tones == []
    assert json.loads(await h.tools.dispatch("transfer", {})) == {"transferred": True}
    assert h.backend.ended == ["call_transfer"]
    assert all(e["mocked"] for e in h.events())


async def test_end_call_ends_the_simulated_call() -> None:
    h = make([tool("end_call", "end_call", {"message": "Bye"})], simulation=True)
    await h.tools.dispatch("end_call", {})
    assert h.backend.said == ["Bye"] and h.backend.ended == ["agent_hangup"]


async def test_kb_search_runs_for_real_in_simulations() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [], "embedding_ms": 1, "query_ms": 1, "embedding_cache_hit": False},
        )

    h = make([], simulation=True, knowledge=[{"kb_id": "kb_1", "name": "FAQ"}], api_handler=api)
    await h.tools.dispatch("kb_search", {"query": "x"})
    assert h.events()[0]["mocked"] is False
