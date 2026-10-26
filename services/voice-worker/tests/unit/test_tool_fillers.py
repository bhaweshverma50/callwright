"""Spoken fillers for tool calls (voice-speed requirement on 005).

* The first tool call of a reply that said nothing yet makes the agent say a filler at once.
* Text already spoken in the reply, internal tools (voicemail detection) and non-lookup tools
  get no filler.
* A lookup still running after about 3 s adds "Still checking, thanks for waiting." once.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
from livekit.agents import llm

from tests.unit.conftest import make_runtime
from tests.unit.tool_support import http_spec, make, tool
from worker.adapters.registry import AdapterRegistry
from worker.pipeline import build_agent, plan_session, with_fillers
from worker.tools.registry import STILL_CHECKING, FillerPolicy


def text(content: str) -> llm.ChatChunk:
    return llm.ChatChunk(id="c", delta=llm.ChoiceDelta(role="assistant", content=content))


def call(name: str) -> llm.ChatChunk:
    fn = llm.FunctionToolCall(name=name, arguments="{}", call_id=f"call_{name}")
    return llm.ChatChunk(id="c", delta=llm.ChoiceDelta(role="assistant", tool_calls=[fn]))


async def stream(*chunks: Any) -> AsyncIterator[Any]:
    for chunk in chunks:
        yield chunk


async def collect(policy: FillerPolicy | None, *chunks: Any) -> list[Any]:
    return [c async for c in with_fillers(stream(*chunks), policy)]


POLICY = {
    "check_availability": "One moment while I check that.",
    "kb_search": "One moment, let me check that.",
}


async def test_filler_said_at_once_before_a_silent_tool_call() -> None:
    policy = FillerPolicy(dict(POLICY))
    out = await collect(policy, call("kb_search"))
    assert out[0] == "One moment, let me check that. " and out[1].delta.tool_calls
    assert policy.reply_spoke is True


async def test_no_filler_when_the_reply_already_spoke() -> None:
    policy = FillerPolicy(dict(POLICY))
    out = await collect(policy, text("Let me look that up."), call("check_availability"))
    assert not any(isinstance(c, str) for c in out)
    assert policy.reply_spoke is True


async def test_internal_and_non_lookup_tools_get_no_filler() -> None:
    policy = FillerPolicy(dict(POLICY))
    for name in ("report_answering_machine", "end_call", "press_digit"):
        out = await collect(policy, call(name))
        assert not any(isinstance(c, str) for c in out), name
        assert policy.reply_spoke is False


async def test_policy_resets_for_each_reply() -> None:
    policy = FillerPolicy(dict(POLICY), reply_spoke=True)
    await collect(policy, text("Hello"))
    assert policy.reply_spoke is False, "a reply without tool calls leaves it reset"
    assert await collect(None, text("x")) == [text("x")]


async def test_still_checking_after_a_long_lookup() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.25)
        return httpx.Response(200, json={"ok": True})

    h = make([http_spec(speak_during_execution=False)], handler=slow)
    h.tools.fillers.texts["check_availability"] = "One moment."  # a lookup with a filler
    h.tools.still_checking_after_s = 0.1
    await h.tools.dispatch("check_availability", {"date": "d"})
    assert h.backend.said == [STILL_CHECKING]

    quick = make([http_spec()], handler=lambda r: httpx.Response(200, json={}))
    quick.tools.still_checking_after_s = 0.1
    await quick.tools.dispatch("check_availability", {"date": "d"})
    assert STILL_CHECKING not in quick.backend.said


async def test_no_still_checking_for_call_control_tools() -> None:
    h = make([tool("end_call", "end_call", {"message": "Bye"})])
    h.tools.still_checking_after_s = 0.0
    await h.tools.dispatch("end_call", {})
    assert h.backend.said == ["Bye"]


def test_agent_receives_the_policy() -> None:
    runtime = make_runtime({"tools": [http_spec()]})
    plan = plan_session(runtime, AdapterRegistry())
    h = make([http_spec()])
    agent = build_agent(plan, runtime, h.tools.control)
    assert agent._fillers is not None and "check_availability" in agent._fillers.texts
