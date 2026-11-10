"""LiveCall event handling without LiveKit: fake job context, session events as namespaces."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from livekit.agents import tts as lk_tts

from tests.harness.runner import CALL_ID
from tests.unit.conftest import call_tools, make_runtime
from worker.adapters.registry import AdapterRegistry
from worker.call_behavior import DtmfCollector
from worker.control import RuntimeCallControl
from worker.entry import LiveCall
from worker.flow import FlowRunner
from worker.flow.runtime import CallwrightFlowRunner
from worker.internal_api import InternalApiClient
from worker.pipeline import OverrideManager, plan_session
from worker.settings import WorkerSettings

BASE = "http://api.test/v1/internal"
OK = {"accepted": 1, "duplicates": 0, "control": {"action": "none"}}


class Emitter:
    """The ``on``/``emit`` surface of a LiveKit session or room."""

    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: Any) -> None:
        for handler in self.handlers.get(event, []):
            handler(payload)


class Room(Emitter):
    name = "call-room"

    def __init__(self) -> None:
        super().__init__()
        self.local_participant: Any = None


class Ctx:
    def __init__(self) -> None:
        self.room = Room()
        self.deleted = 0
        self.shutdowns: list[str] = []
        self.done = asyncio.Event()  # set once the call has been torn down

    async def delete_room(self) -> None:
        self.deleted += 1

    def shutdown(self, reason: str = "") -> None:
        self.shutdowns.append(reason)
        self.done.set()


class Session(Emitter):
    def __init__(self) -> None:
        super().__init__()
        self.interrupted = 0
        self.closed = 0
        self.replies: list[str] = []
        self.agents: list[Any] = []

    def interrupt(self) -> None:
        self.interrupted += 1

    async def aclose(self) -> None:
        self.closed += 1

    def generate_reply(self, user_input: str) -> None:
        self.replies.append(user_input)

    def update_agent(self, agent: Any) -> None:
        self.agents.append(agent)


async def no_sleep(_: float) -> None:
    return None


def live_call(
    flows: FlowRunner | None = None,
    registry: AdapterRegistry | None = None,
    **config: Any,
) -> tuple[LiveCall, Ctx, Session]:
    """A call wired like ``LiveCall.run`` wires it, up to the session: events go in through the
    session and room emitters, and the call is over when ``ctx.done`` is set."""
    ctx = Ctx()
    runtime = make_runtime(dict(config))
    api = InternalApiClient(BASE, "t", sleep=no_sleep)
    call = LiveCall(
        ctx,
        api,
        WorkerSettings(),
        CALL_ID,
        runtime,
        registry,
        flows=flows or CallwrightFlowRunner(),
    )
    call.plan = plan_session(runtime, call.registry, call.flows)
    call.overrides = OverrideManager(
        call.plan, call.registry, runtime.controls, runtime.stt_auto_rules
    )
    call.control = RuntimeCallControl(
        CALL_ID,
        call.recorder,
        call,
        overrides=call.overrides,
        on_overrides_staged=call.request_swap,
    )
    session = Session()
    call.session = session
    call.wire(session, call.plan)
    return call, ctx, session


def ev(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def agent_state(session: Session, old: str, new: str, at: float) -> None:
    session.emit("agent_state_changed", ev(old_state=old, new_state=new, created_at=at))


def user_state(session: Session, old: str, new: str, at: float) -> None:
    session.emit("user_state_changed", ev(old_state=old, new_state=new, created_at=at))


def item(session: Session, role: str, text: str, **extra: Any) -> None:
    session.emit("conversation_item_added", ev(item=ev(role=role, text_content=text, **extra)))


def test_turn_events_from_session_state_changes() -> None:
    call, _, session = live_call()
    call.tracker.connected(100.0)
    call.tracker.begin_turn(greeting=True)
    agent_state(session, "listening", "speaking", 100.3)
    item(session, "assistant", "Hi there", interrupted=False)
    user_state(session, "listening", "speaking", 101.0)
    user_state(session, "speaking", "listening", 102.0)
    item(session, "user", "Hello", transcript_confidence=0.9)
    agent_state(session, "listening", "thinking", 102.1)
    agent_state(session, "thinking", "speaking", 102.65)
    item(session, "assistant", "How can", interrupted=True)
    events = call.recorder.drain()
    turns = [e for e in events if e["type"] == "turn"]
    assert [(t["turn_index"], t["e2e_ms"], t["interrupted"]) for t in turns] == [
        (0, 300, False),
        (1, 650, True),
    ]
    messages = [e["item"] for e in events if e["type"] == "transcript_item"]
    assert [(m["role"], m["text"]) for m in messages] == [
        ("agent", "Hi there"),
        ("user", "Hello"),
        ("agent", "How can"),
    ]


class Publisher:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[dict[str, Any], bool, str]] = []
        self.fail = fail
        self.attempted = asyncio.Event()

    async def publish_data(self, data: bytes, *, reliable: bool, topic: str) -> None:
        self.attempted.set()
        if self.fail:
            raise RuntimeError("room closed")
        self.sent.append((json.loads(data), reliable, topic))


async def test_agent_turns_publish_latency_on_the_data_topic() -> None:
    call, ctx, session = live_call()
    publisher = Publisher()
    ctx.room.local_participant = publisher
    call.tracker.connected(100.0)
    call.tracker.begin_turn(greeting=True)
    agent_state(session, "listening", "speaking", 100.3)
    item(session, "assistant", "Hi there", interrupted=False)
    user_state(session, "listening", "speaking", 101.0)
    user_state(session, "speaking", "listening", 102.0)
    agent_state(session, "listening", "thinking", 102.1)
    call.tracker.component("llm_ttft", 0.3)
    call.tracker.component("tts_ttfb", 0.15)
    agent_state(session, "thinking", "speaking", 102.65)
    item(session, "assistant", "Sure", interrupted=False)
    await asyncio.wait_for(publisher.attempted.wait(), 2)
    # The greeting has no chip; the answer's parts add up to its measured 650 ms.
    assert publisher.sent == [
        (
            {"turn_index": 1, "stt_ms": 200, "llm_ms": 300, "tts_ms": 150, "e2e_ms": 650},
            True,
            "cw.turn_latency",
        )
    ]


async def test_latency_publish_failure_does_not_break_the_call() -> None:
    call, ctx, session = live_call()
    publisher = Publisher(fail=True)
    ctx.room.local_participant = publisher
    call.tracker.connected(100.0)
    call.tracker.begin_turn()
    call.tracker.component("llm_ttft", 0.3)
    item(session, "assistant", "Sure", interrupted=False)
    await asyncio.wait_for(publisher.attempted.wait(), 2)
    assert [e["type"] for e in call.recorder.drain()] == ["turn", "transcript_item"]


def press(ctx: Ctx, keys: str) -> None:
    for key in keys:
        ctx.room.emit("sip_dtmf_received", ev(digit=key))


def with_keypad(call: LiveCall) -> None:
    assert call.plan is not None
    call.dtmf = DtmfCollector(call.clock, call.plan.behavior.dtmf, call.on_dtmf_flush)


async def test_keypad_flush_becomes_a_user_turn() -> None:
    call, ctx, session = live_call()
    with_keypad(call)
    press(ctx, "1234#")
    assert session.replies == ["1234"]
    kinds = [e["type"] for e in call.recorder.drain()]
    assert kinds == ["dtmf", "transcript_item"]


async def test_keypad_turn_is_one_caller_line() -> None:
    """The session echoes the keypad input as a user item (003 quickstart section 8: ``1234#``
    is one caller turn): it is not recorded again as speech, but later speech still is."""
    call, ctx, session = live_call()
    with_keypad(call)
    press(ctx, "1234#")
    item(session, "user", "1234")
    item(session, "user", "1234")
    lines = [e["item"] for e in call.recorder.drain() if e["type"] == "transcript_item"]
    assert [(i["text"], i.get("source")) for i in lines] == [("1234", "keypad"), ("1234", "voice")]


@respx.mock
async def test_hang_up_posts_final_status_and_deletes_room() -> None:
    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(200, json=OK)
    )
    call, ctx, session = live_call()
    assert call.control is not None
    assert await call.control.hang_up("max_duration_reached")
    assert not await call.control.hang_up("user_hangup")
    await asyncio.wait_for(ctx.done.wait(), 2)
    events = json.loads(route.calls.last.request.content)["events"]
    assert [e["type"] for e in events] == ["transcript_item", "status", "usage"]
    assert events[0]["item"]["event"] == "max_duration"
    assert events[1]["disconnect_reason"] == "max_duration_reached"
    assert session.interrupted == 1 and session.closed == 1
    assert ctx.deleted == 1 and ctx.shutdowns == ["call ended"]


@respx.mock
async def test_control_end_call_from_heartbeat_ends_the_call() -> None:
    respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    **OK,
                    "control": {"action": "end_call", "disconnect_reason": "insufficient_credit"},
                },
            ),
            httpx.Response(200, json=OK),
        ]
    )
    call, ctx, _ = live_call()
    await call.poster.flush()
    await asyncio.wait_for(ctx.done.wait(), 2)
    assert call.control is not None and call.control.disconnect_reason == "insufficient_credit"
    assert ctx.deleted == 1


class Tts(lk_tts.TTS):  # type: ignore[type-arg]
    def __init__(self) -> None:
        super().__init__(
            capabilities=lk_tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1
        )

    def synthesize(self, text: str, **_: Any) -> Any:
        raise NotImplementedError


@respx.mock
async def test_vendor_error_ends_the_call_with_its_diagnostic() -> None:
    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(200, json=OK)
    )
    _, ctx, session = live_call()
    session.emit("error", ev(error=ev(recoverable=True, error="retry"), source=Tts()))
    session.emit("error", ev(error=ev(recoverable=False, error="boom"), source=Tts()))
    await asyncio.wait_for(ctx.done.wait(), 2)
    posted = [e for r in route.calls for e in json.loads(r.request.content)["events"]]
    codes = [e["code"] for e in posted if e["type"] in ("warning", "error")]
    assert codes == ["vendor_retry", "vendor_error"]
    (status,) = [e for e in posted if e["type"] == "status"]
    assert status["disconnect_reason"] == "error"
    assert status["diagnostic"] == "vendor_error:tts/elevenlabs"
    system = [e["item"] for e in posted if e["type"] == "transcript_item"]
    assert [(i["event"], i["detail"]) for i in system] == [
        ("vendor_error", "vendor_error:tts/elevenlabs")
    ]


@respx.mock
@pytest.mark.usefixtures("no_llm_prewarm")
async def test_end_call_from_inside_the_session_closes_it_promptly() -> None:
    """Regression (lab call, 2026-11-03): end_call hangs up from inside its own tool call, and
    the hang-up used to await the session's close, which waits for that very tool. LiveKit
    cancelled the tool after its interruption timeout, the room stayed open and the job was
    killed after ``AgentSession.aclose()`` timed out. Now the close runs on its own and the
    call is torn down at once, with end_call's own event before the final status."""
    from livekit.agents import AgentSession

    from tests.flow_support import FlowScript, Rule, flow_llm
    from worker.pipeline import build_agent
    from worker.tools.registry import build_call_tools

    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(200, json=OK)
    )
    call, ctx, _ = live_call()
    assert call.control is not None and call.plan is not None
    tools = build_call_tools(call.runtime, call.control)
    agent = build_agent(call.plan, call.runtime, call.control, tools)
    model = flow_llm(FlowScript(rules=[Rule("bye", "end_call", {"goodbye": "Bye for now."})]))
    session: Any = AgentSession(llm=model, vad=None)
    call.session = session
    await session.start(agent)
    started = asyncio.get_running_loop().time()
    session.run(user_input="That's all, bye")
    await asyncio.wait_for(ctx.done.wait(), 5)
    assert asyncio.get_running_loop().time() - started < 3
    assert call.control.disconnect_reason == "agent_hangup"
    assert ctx.deleted == 1 and ctx.shutdowns == ["call ended"]
    assert not session._started  # closed, not left half-open for the job's shutdown
    posted = [e for r in route.calls for e in json.loads(r.request.content)["events"]]
    kinds = [e["type"] for e in posted]
    assert "tool_call" in kinds and kinds.index("tool_call") < kinds.index("status")


async def test_caller_quiet_waits_for_words_not_for_line_noise() -> None:
    call, _, session = live_call()
    assert await call.caller_quiet(0.2, 0.0)  # nothing heard yet
    session.emit("user_input_transcribed", ev(transcript="Can you call me", is_final=False))
    assert not await call.caller_quiet(0.2, 0.05)  # words in the last 0.2 s
    assert await call.caller_quiet(0.05, 0.5)  # quiet once they stop
    user_state(session, "listening", "speaking", 1.0)
    started = asyncio.get_running_loop().time()
    # Voice activity without words (line noise) never keeps the call open past the wait.
    assert await call.caller_quiet(0.05, 0.1)
    assert asyncio.get_running_loop().time() - started >= 0.1
    user_state(session, "speaking", "listening", 2.0)
    assert await call.caller_quiet(0.05, 0.0)


async def test_language_swap_on_a_flow_call_rebuilds_its_current_node() -> None:
    """012 on flows: the swap at the turn boundary rebuilds the node the call is on with the new
    plan and components; building the entry agent again would restart the flow."""
    from tests.flow_support import compiled_config
    from worker.pipeline import SessionComponents

    rebuilt: list[tuple[str, Any, Mapping[str, Any]]] = []

    class Runner(CallwrightFlowRunner):
        def rebuild(self, call_id: str, plan: Any, components: Mapping[str, Any]) -> str:
            rebuilt.append((call_id, plan, components))
            return "node-agent"

    registry = AdapterRegistry().with_builders(
        default_builder=lambda spec, creds: f"new-{spec.kind}"
    )
    call, _, session = live_call(Runner(), registry, **compiled_config("greeting_end"))
    assert call.plan is not None and call.plan.agent_type == "flow"
    assert call.control is not None
    call.components = SessionComponents(stt="stt", llm="llm", tts="tts", nc=None)
    call.tools = call_tools(call.runtime)
    agent_state(session, "idle", "thinking", 1.0)  # mid-turn: the swap waits for the boundary
    await call.control.apply_overrides(
        {
            "switch_language": {"code": "hi", "label": "Hindi", "tts_model": None},
            "stt": {"language": "hi", "model": "nova-2"},
        }
    )
    assert rebuilt == []
    agent_state(session, "thinking", "listening", 2.0)
    ((call_id, plan, components),) = rebuilt
    assert call_id == CALL_ID
    assert plan.reply_language == "Hindi" and plan.language == "hi"
    assert components["stt"] == "new-stt" and components["llm"] == "llm"
    assert session.agents == ["node-agent"]
