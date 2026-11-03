"""SIP ring phase and outbound dialling (010 T015, T029, research R5, R6).

A fake SIP service answers, rejects with a status code or times out; a fake room raises
``participant_disconnected``. Inbound: ``ringing`` then answered after the ring duration, and a
caller who hangs up while it rings is ``failed`` without ever connecting. Outbound: ``ringing``
then the callee, or ``busy``/``no_answer``/``failed`` with the mapped diagnostic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from tests.harness.fakes import FakeSipDialer, FakeSipRoom
from tests.harness.runner import CALL_ID
from tests.unit.conftest import make_runtime
from worker.adapters.registry import AdapterRegistry
from worker.entry import LiveCall
from worker.internal_api import InternalApiClient, OutboundDial
from worker.metrics import EventRecorder, UsageMeters
from worker.pipeline import plan_session
from worker.settings import WorkerSettings
from worker.telephony import (
    RINGBACK_RATE,
    DialFailed,
    dial,
    map_sip_status,
    ring_phase,
    ringback_cycle,
)

SPEC = OutboundDial(
    sip_trunk_id="ST_out", to_number="+14155550199", from_number="+14155550100", ring_timeout_s=20
)
BASE = "http://api.test/v1/internal"
OK = {"accepted": 1, "duplicates": 0, "control": {"action": "none"}}


def statuses(recorder: EventRecorder) -> list[dict[str, Any]]:
    return [
        {
            k: v
            for k, v in e.items()
            if k in ("status", "diagnostic", "sip_status_code", "disconnect_reason")
        }
        for e in recorder.drain()
        if e["type"] == "status"
    ]


@pytest.mark.parametrize(
    ("code", "timed_out", "expected"),
    [
        (486, False, ("busy", "sip_486")),
        (600, False, ("busy", "sip_600")),
        (408, False, ("no_answer", "sip_408")),
        (480, False, ("no_answer", "sip_480")),
        (487, False, ("no_answer", "sip_487")),
        (None, True, ("no_answer", "ring_timeout")),
        (403, False, ("failed", "sip_403")),
        (404, False, ("failed", "sip_404")),
        (484, False, ("failed", "sip_484")),
        (503, False, ("failed", "sip_503")),
        (401, False, ("failed", "trunk_auth_failed")),
        (407, False, ("failed", "trunk_auth_failed")),
        (None, False, ("failed", "trunk_unreachable")),
    ],
)
def test_sip_status_mapping(code: int | None, timed_out: bool, expected: tuple[str, str]) -> None:
    assert map_sip_status(code, timed_out=timed_out) == expected


async def test_dial_answered() -> None:
    recorder = EventRecorder(UsageMeters())
    dialer = FakeSipDialer(answer=True)
    callee = SimpleNamespace(identity="callee")

    async def wait() -> Any:
        return callee

    assert await dial(dialer, recorder, SPEC, "call-room", wait) is callee
    assert dialer.calls == [
        {
            "room_name": "call-room",
            "trunk_id": "ST_out",
            "to_number": "+14155550199",
            "from_number": "+14155550100",
            "identity": "callee",
            "ring_timeout_s": 20,
        }
    ]
    assert statuses(recorder) == [{"status": "ringing"}]


@pytest.mark.parametrize(
    ("dialer", "expected"),
    [
        (FakeSipDialer(reject=486), ("busy", "sip_486", 486)),
        (FakeSipDialer(reject=480), ("no_answer", "sip_480", 480)),
        (FakeSipDialer(time_out=True), ("no_answer", "ring_timeout", None)),
        (FakeSipDialer(reject=503), ("failed", "sip_503", 503)),
        (FakeSipDialer(reject=407), ("failed", "trunk_auth_failed", 407)),
        (FakeSipDialer(unreachable=True), ("failed", "trunk_unreachable", None)),
    ],
)
async def test_dial_not_answered(
    dialer: FakeSipDialer, expected: tuple[str, str, int | None]
) -> None:
    recorder = EventRecorder(UsageMeters())

    async def wait() -> Any:
        raise AssertionError("never waits for a callee that did not answer")

    with pytest.raises(DialFailed) as exc:
        await dial(dialer, recorder, SPEC, "call-room", wait)
    assert (exc.value.status, exc.value.diagnostic, exc.value.sip_status_code) == expected


def _sleeper(room: FakeSipRoom, *, hang_up_after: float | None) -> Callable[[float], Any]:
    async def sleep(seconds: float) -> None:
        if hang_up_after is not None and hang_up_after < seconds:
            await asyncio.sleep(0)
            room.disconnect("sip_caller")
            await asyncio.Event().wait()  # the ring timer never fires first
        await asyncio.sleep(0)

    return sleep


async def test_ring_phase_answers_after_ring_duration() -> None:
    room = FakeSipRoom(["sip_caller"])
    recorder = EventRecorder(UsageMeters())
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    assert await ring_phase(room, recorder, 3000, "sip_caller", sleep=sleep)
    assert slept == [3.0] and statuses(recorder) == [{"status": "ringing"}]
    assert room.handlers["participant_disconnected"] == []  # listener removed


async def test_caller_hangs_up_while_ringing() -> None:
    room = FakeSipRoom(["sip_caller"])
    recorder = EventRecorder(UsageMeters())
    answered = await ring_phase(
        room, recorder, 5000, "sip_caller", sleep=_sleeper(room, hang_up_after=1.0)
    )
    assert answered is False


async def test_another_participant_leaving_does_not_stop_the_ring() -> None:
    room = FakeSipRoom(["sip_caller", "someone"])
    recorder = EventRecorder(UsageMeters())

    async def sleep(seconds: float) -> None:
        room.disconnect("someone")
        await asyncio.sleep(0)

    assert await ring_phase(room, recorder, 1000, "sip_caller", sleep=sleep)


async def test_ringback_plays_only_while_ringing() -> None:
    room = FakeSipRoom(["sip_caller"])
    recorder = EventRecorder(UsageMeters())
    played: list[str] = []

    async def ringback() -> None:
        played.append("start")
        try:
            await asyncio.Event().wait()
        finally:
            played.append("stop")

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    assert await ring_phase(room, recorder, 2000, "sip_caller", sleep=sleep, ringback=ringback)
    assert played == ["start", "stop"]
    played.clear()
    assert await ring_phase(room, recorder, 0, "sip_caller", sleep=sleep, ringback=ringback)
    assert played == [], "no ring time, no tone"


def test_ringback_cycle_is_a_double_ring() -> None:
    cycle = ringback_cycle()
    assert len(cycle) == RINGBACK_RATE * 3

    def loud(a: float, b: float) -> bool:
        part = cycle[int(a * RINGBACK_RATE) : int(b * RINGBACK_RATE)]
        return max(abs(v) for v in part) > 1000

    assert loud(0.05, 0.35) and not loud(0.42, 0.58) and loud(0.65, 0.95) and not loud(1.05, 2.95)
    assert max(abs(v) for v in cycle) < 32767 * 0.2  # quiet, never clipping


# LiveCall wiring ----------------------------------------------------------------------------


class Ctx:
    def __init__(self, room: Any) -> None:
        self.room = room
        self.deleted = 0
        self.shutdowns: list[str] = []
        self.api = SimpleNamespace()

    async def delete_room(self) -> None:
        self.deleted += 1

    def shutdown(self, reason: str = "") -> None:
        self.shutdowns.append(reason)

    async def wait_for_participant(self, *, identity: str | None = None) -> Any:
        return SimpleNamespace(identity=identity or "sip_caller", attributes={})


async def no_sleep(_: float) -> None:
    return None


def _call(channel: str, **runtime: Any) -> tuple[LiveCall, Ctx]:
    ctx = Ctx(FakeSipRoom(["sip_caller"]))
    config = make_runtime({"call_behavior": {"ring_duration_ms": 0}}, channel=channel, **runtime)
    api = InternalApiClient(BASE, "t", sleep=no_sleep)
    call = LiveCall(ctx, api, WorkerSettings(), CALL_ID, config)
    call.plan = plan_session(config, AdapterRegistry())
    return call, ctx


@respx.mock
async def test_outbound_busy_is_posted_and_room_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    posted = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(200, json=OK)
    )
    call, ctx = _call("sip_outbound", outbound_dial=SPEC.model_dump())

    async def busy(_ctx: Any, _spec: Any, recorder: Any, dialer: Any = None) -> Any:
        recorder.status("ringing")
        raise DialFailed("busy", "sip_486", 486)

    monkeypatch.setattr("worker.entry.dial_outbound", busy)
    assert await call._await_caller() is None
    sent = [e for request in posted.calls for e in json.loads(request.request.content)["events"]]
    assert [
        (e["status"], e.get("diagnostic"), e.get("sip_status_code"))
        for e in sent
        if e["type"] == "status"
    ] == [
        ("ringing", None, None),
        ("busy", "sip_486", 486),
    ]
    assert ctx.deleted == 1 and call.connected_at is None


@respx.mock
async def test_inbound_caller_hangup_during_ring_fails_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(200, json=OK)
    )
    call, ctx = _call("sip_inbound")

    async def hung_up(room: Any, recorder: Any, ring_ms: int, identity: str, **_: Any) -> bool:
        recorder.status("ringing")
        return False

    monkeypatch.setattr("worker.entry.ring_phase", hung_up)
    assert await call._await_caller() is None
    sent = [e for request in posted.calls for e in json.loads(request.request.content)["events"]]
    assert [(e["status"], e.get("diagnostic")) for e in sent if e["type"] == "status"] == [
        ("ringing", None),
        ("failed", "caller_hung_up_while_ringing"),
    ]
    assert ctx.deleted == 1 and call.connected_at is None


async def test_inbound_answered_after_ring() -> None:
    call, _ = _call("whatsapp")
    participant = await call._await_caller()
    assert participant is not None and participant.identity == "sip_caller"
    assert statuses(call.recorder) == [{"status": "ringing"}]


async def test_caller_hangup_after_connect_is_user_hangup() -> None:
    call, _ = _call("sip_inbound")
    call.caller_identity = "sip_caller"
    reasons: list[str] = []
    call._hang_up_soon = lambda reason, diagnostic=None: reasons.append(reason)  # type: ignore[method-assign]
    call._on_participant_left(SimpleNamespace(identity="sip_caller"))
    assert reasons == ["user_hangup"]
