"""The real livekit-agents AgentSession runs the Callwright agent offline in text mode."""

from __future__ import annotations

from typing import Any

from livekit.agents import AgentSession

from tests.harness.fakes import scripted_llm
from tests.unit.conftest import call_tools, make_runtime
from worker.adapters.registry import AdapterRegistry
from worker.metrics import LatencyTracker, MetricsBridge, UsageMeters
from worker.pipeline import build_agent, plan_session


async def test_agent_session_replies_with_rendered_instructions() -> None:
    runtime = make_runtime(variables={"company_name": "Northwind", "customer_name": "Priya"})
    plan = plan_session(runtime, AdapterRegistry())
    llm = scripted_llm("Your balance is 42 dollars.")
    agent = build_agent(plan, runtime, None, call_tools(runtime))  # type: ignore[arg-type]
    meters = UsageMeters()
    tracker = LatencyTracker()
    bridge = MetricsBridge(tracker, meters, lambda kind: ("azure_openai", "gpt-5.1"))
    async with AgentSession(llm=llm, vad=None) as session:
        session.on("metrics_collected", lambda ev: bridge.on_metrics(ev.metrics))
        await session.start(agent)
        result: Any = await session.run(user_input="What is my balance?")
    replies = [e.item.text_content for e in result.events if getattr(e, "type", "") == "message"]
    assert replies == ["Your balance is 42 dollars."]
    system = llm.requests[0].items[0]
    assert "receptionist at Northwind" in system.text_content
    assert meters.snapshot()["llm"][0]["input_tokens"] == 100
