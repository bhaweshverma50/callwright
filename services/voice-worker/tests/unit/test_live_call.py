"""LiveCall event handling without LiveKit: fake job context, session events as namespaces."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import respx

from tests.harness.runner import CALL_ID
from tests.unit.conftest import make_runtime
from worker.adapters.registry import AdapterRegistry
from worker.control import RuntimeCallControl
from worker.entry import LiveCall
from worker.internal_api import InternalApiClient
from worker.pipeline import OverrideManager, plan_session
from worker.settings import WorkerSettings

BASE = "http://api.test/v1/internal"
OK = {"accepted": 1, "duplicates": 0, "control": {"action": "none"}}


class Ctx:
    def __init__(self) -> None:
        self.room = SimpleNamespace(name="call-room")
        self.deleted = 0
        self.shutdowns: list[str] = []

    async def delete_room(self) -> None:
        self.deleted += 1

    def shutdown(self, reason: str = "") -> None:
        self.shutdowns.append(reason)


class Session:
    def __init__(self) -> None:
        self.interrupted = 0
        self.closed = 0
        self.replies: list[str] = []

    def interrupt(self) -> None:
        self.interrupted += 1

    async def aclose(self) -> None:
        self.closed += 1

    def generate_reply(self, user_input: str) -> None:
        self.replies.append(user_input)


async def no_sleep(_: float) -> None:
    return None


def live_call(**config: Any) -> tuple[LiveCall, Ctx, Session]:
    ctx = Ctx()
    runtime = make_runtime(dict(config))
    api = InternalApiClient(BASE, "t", sleep=no_sleep)
    call = LiveCall(ctx, api, WorkerSettings(), CALL_ID, runtime)
    call.plan = plan_session(runtime, AdapterRegistry())
    call.overrides = OverrideManager(call.plan, AdapterRegistry())
    call.control = RuntimeCallControl(CALL_ID, call.recorder, call, overrides=call.overrides)
    session = Session()
    call.session = session
    return call, ctx, session


def ev(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def test_turn_events_from_session_state_changes() -> None:
    call, _, _ = live_call()
    call.tracker.connected(100.0)
    call.tracker.begin_turn(greeting=True)
    call._on_agent_state(ev(old_state="listening", new_state="speaking", created_at=100.3))
    call._on_item(ev(item=ev(role="assistant", text_content="Hi there", interrupted=False)))
    call._on_user_state(ev(old_state="listening", new_state="speaking", created_at=101.0))
    call._on_user_state(ev(old_state="speaking", new_state="listening", created_at=102.0))
    call._on_item(ev(item=ev(role="user", text_content="Hello", transcript_confidence=0.9)))
    call._on_agent_state(ev(old_state="listening", new_state="thinking", created_at=102.1))
    call._on_agent_state(ev(old_state="thinking", new_state="speaking", created_at=102.65))
    call._on_item(ev(item=ev(role="assistant", text_content="How can", interrupted=True)))
    turns = [e for e in call.recorder.history if e["type"] == "turn"]
    assert [(t["turn_index"], t["e2e_ms"], t["interrupted"]) for t in turns] == [
        (0, 300, False),
        (1, 650, True),
    ]
    messages = [e["item"] for e in call.recorder.history if e["type"] == "transcript_item"]
    assert [(m["role"], m["text"]) for m in messages] == [
        ("agent", "Hi there"),
        ("user", "Hello"),
        ("agent", "How can"),
    ]


class Publisher:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[dict[str, Any], bool, str]] = []
        self.fail = fail

    async def publish_data(self, data: bytes, *, reliable: bool, topic: str) -> None:
        if self.fail:
            raise RuntimeError("room closed")
        self.sent.append((json.loads(data), reliable, topic))


async def test_agent_turns_publish_latency_on_the_data_topic() -> None:
    call, ctx, _ = live_call()
    publisher = Publisher()
    ctx.room.local_participant = publisher
    call.tracker.connected(100.0)
    call.tracker.begin_turn(greeting=True)
    call._on_agent_state(ev(old_state="listening", new_state="speaking", created_at=100.3))
    call._on_item(ev(item=ev(role="assistant", text_content="Hi there", interrupted=False)))
    call._on_user_state(ev(old_state="listening", new_state="speaking", created_at=101.0))
    call._on_user_state(ev(old_state="speaking", new_state="listening", created_at=102.0))
    call._on_agent_state(ev(old_state="listening", new_state="thinking", created_at=102.1))
    call.tracker.component("llm_ttft", 0.3)
    call.tracker.component("tts_ttfb", 0.15)
    call._on_agent_state(ev(old_state="thinking", new_state="speaking", created_at=102.65))
    call._on_item(ev(item=ev(role="assistant", text_content="Sure", interrupted=False)))
    await asyncio.gather(*call._tasks)
    # The greeting has no chip; the answer's parts add up to its measured 650 ms.
    assert publisher.sent == [
        (
            {"turn_index": 1, "stt_ms": 200, "llm_ms": 300, "tts_ms": 150, "e2e_ms": 650},
            True,
            "cw.turn_latency",
        )
    ]


async def test_latency_publish_failure_does_not_break_the_call() -> None:
    call, ctx, _ = live_call()
    ctx.room.local_participant = Publisher(fail=True)
    call.tracker.connected(100.0)
    call.tracker.begin_turn()
    call.tracker.component("llm_ttft", 0.3)
    call._on_item(ev(item=ev(role="assistant", text_content="Sure", interrupted=False)))
    await asyncio.gather(*call._tasks)
    assert [e["type"] for e in call.recorder.history] == ["turn", "transcript_item"]


async def test_keypad_flush_becomes_a_user_turn() -> None:
    call, _, session = live_call()
    call._on_dtmf_flush("1234", "termination_key")
    assert session.replies == ["1234"]
    kinds = [e["type"] for e in call.recorder.history]
    assert kinds == ["dtmf", "transcript_item"]


@respx.mock
async def test_hang_up_posts_final_status_and_deletes_room() -> None:
    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(200, json=OK)
    )
    call, ctx, session = live_call()
    assert call.control is not None
    assert await call.control.hang_up("max_duration_reached")
    assert not await call.control.hang_up("user_hangup")
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
    for task in list(call._tasks):
        await task
    assert call.control is not None and call.control.disconnect_reason == "insufficient_credit"
    assert ctx.deleted == 1


def test_vendor_error_ends_call_with_diagnostic() -> None:
    call, _, _ = live_call()
    hung: list[tuple[str, str | None]] = []
    call._hang_up_soon = lambda reason, diagnostic=None: hung.append((reason, diagnostic))  # type: ignore[method-assign]
    from livekit.agents import tts as lk_tts

    class Tts(lk_tts.TTS):  # type: ignore[type-arg]
        def __init__(self) -> None:
            super().__init__(
                capabilities=lk_tts.TTSCapabilities(streaming=False),
                sample_rate=24000,
                num_channels=1,
            )

        def synthesize(self, text: str, **_: Any) -> Any:
            raise NotImplementedError

    assert call.plan is not None
    call._on_error(ev(error=ev(recoverable=False, error="boom"), source=Tts()), call.plan)
    call._on_error(ev(error=ev(recoverable=True, error="retry"), source=Tts()), call.plan)
    assert hung == [("error", "vendor_error:tts/elevenlabs")]
    codes = [e["code"] for e in call.recorder.history if e["type"] in ("warning", "error")]
    assert codes == ["vendor_error", "vendor_retry"]
