"""No outbound network from simulations (008 T015, research R4, FR-013): a simulated session
opens no socket and sends no HTTP request outside the allow-list (the LLM adapters and the
internal API), and never builds an HTTP tool or webhook executor, even for tools and webhook
nodes without a mock."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.flow_support import Rule
from tests.harness.textsim_support import (
    BASE,
    FakeInternalApi,
    Models,
    agent_config,
    agent_script,
    case_spec,
    deps,
    flow,
    http_tool,
    sim_spec,
)
from worker.textsim import runner
from worker.textsim.llm import ScriptReply
from worker.tools.http import HttpExecutor

# In production the allow-list also holds the configured LLM adapters' hosts; here every model
# is scripted in process, so only the (mocked) internal API may be addressed.
ALLOWED_HOSTS = {httpx.URL(BASE).host}


@pytest.fixture
def egress(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    attempts: list[str] = []

    def deny(kind: str) -> Any:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            attempts.append(f"{kind} {args[1:] if kind.startswith('socket.') else args}")
            raise OSError(f"egress blocked: {kind}")

        return blocked

    monkeypatch.setattr(socket.socket, "connect", deny("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", deny("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", deny("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", deny("getaddrinfo"))

    real_send = httpx.AsyncClient.send

    async def send(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> Any:
        if request.url.host not in ALLOWED_HOSTS:
            attempts.append(f"http {request.method} {request.url}")
            raise httpx.ConnectError("egress blocked", request=request)
        return await real_send(self, request, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    def no_http_executor(*args: Any, **kwargs: Any) -> None:
        attempts.append("HttpExecutor constructed")
        raise AssertionError("HTTP executors must not exist in simulations")

    monkeypatch.setattr(HttpExecutor, "__init__", no_http_executor)
    yield attempts


async def test_replay_with_unmocked_tools_and_kb_makes_no_outbound_connection(
    egress: list[str],
) -> None:
    api = FakeInternalApi()
    config = agent_config(
        tools=[http_tool("orders"), http_tool("refund", mock='{"ok":true}')],
        knowledge=[{"kb_id": "kb_1", "name": "FAQ"}],
        kb_ids=["kb_1"],
    )
    api.sim_specs["srun_1"] = sim_spec(
        config,
        caller_turns=["where is my order", "refund please", "what are your hours"],
        recorded_tool_outputs=[],
    )
    models = Models(
        agent=agent_script(
            [
                Rule("order", tool="orders", args={"ref": "1"}),
                Rule("refund", tool="refund"),
                Rule("hours", tool="kb_search", args={"query": "hours"}),
            ]
        ),
        synth=lambda _: ScriptReply('{"status":"shipped"}'),
    )
    status = await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    assert status == "completed"
    assert egress == []
    counts = api.sim_results["srun_1"]["answer_source_counts"]
    assert counts["synthesized"] == 1 and counts["mock"] == 1
    assert len(api.kb_requests) == 1
    assert {r.url.host for r in api.requests} == ALLOWED_HOSTS


async def test_flow_webhook_without_mock_makes_no_outbound_connection(egress: list[str]) -> None:
    api = FakeInternalApi()
    api.case_specs[("trn_1", "tc_1")] = case_spec(flow("webhook_failure"), "Where is my order?")
    models = Models(
        agent=agent_script([Rule("order", tool="route_to_order_status")]),
        synth=lambda _: ScriptReply('{"status":"late"}'),
    )
    status = await runner.run_single_turn(api.client(), "trn_1", "tc_1", deps(api, models))
    assert status == "completed" and egress == []
    result = api.case_results[("trn_1", "tc_1")]
    assert "n_hook0000" in result["nodes_visited"]
    assert result["tool_calls"][0]["answer_source"] == "synthesized"


async def test_the_guard_catches_a_real_attempt(egress: list[str]) -> None:
    """The fixture is not vacuous: a request outside the allow-list is recorded and blocked."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://api.example.com/orders")
    assert egress == ["http GET https://api.example.com/orders"]


async def test_schedule_callback_is_mocked_in_simulations(egress: list[str]) -> None:
    """011: a simulated caller asking for a callback gets a booked time, and nothing reaches the
    API's booking endpoint (no real callback can be created)."""
    api = FakeInternalApi()
    api.sim_specs["srun_cb"] = sim_spec(
        agent_config(), caller_turns=["can you call me back in an hour"], recorded_tool_outputs=[]
    )
    models = Models(
        agent=agent_script(
            [Rule("call me back", tool="schedule_callback", args={"in_minutes": 60, "note": "x"})]
        ),
    )
    status = await runner.run_simulation(api.client(), "srun_cb", deps(api, models))
    assert status == "completed" and egress == []
    assert not [r for r in api.requests if "callbacks" in r.url.path]
    calls = [e for batch in api.events.values() for e in batch if e.get("type") == "tool_call"]
    booked = [e for e in calls if e.get("name") == "schedule_callback"]
    assert len(booked) == 1 and booked[0]["mocked"] is True and not booked[0]["is_error"]
    assert json.loads(booked[0]["output"])["scheduled"] is True
