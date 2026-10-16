"""Event posting as the heartbeat and end-call handling (R3, FR-025)."""

from __future__ import annotations

import asyncio
import json

import httpx
import respx

from tests.harness.runner import CALL_ID
from worker.internal_api import InternalApiClient
from worker.metrics import EventPoster, EventRecorder, UsageMeters

BASE = "http://api.test/v1/internal"
URL = f"{BASE}/calls/{CALL_ID}/events"
OK = {"accepted": 1, "duplicates": 0, "control": {"action": "none"}}
END = {
    "accepted": 1,
    "duplicates": 0,
    "control": {"action": "end_call", "disconnect_reason": "insufficient_credit"},
}


async def no_sleep(_: float) -> None:
    return None


def make(**kw: object) -> tuple[EventRecorder, EventPoster, list[str]]:
    recorder = EventRecorder(UsageMeters())
    reasons: list[str] = []

    async def on_end(reason: str) -> None:
        reasons.append(reason)

    api = InternalApiClient(BASE, "t", sleep=no_sleep, max_attempts=2)
    poster = EventPoster(CALL_ID, recorder, api, on_end_call=on_end, **kw)  # type: ignore[arg-type]
    return recorder, poster, reasons


def posted(route: respx.Route) -> list[list[dict[str, object]]]:
    return [json.loads(c.request.content)["events"] for c in route.calls]


@respx.mock
async def test_every_flush_carries_a_cumulative_usage_snapshot() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=OK))
    recorder, poster, _ = make()
    recorder.meters.add_tts("elevenlabs", "eleven_flash_v2_5", 10)
    recorder.status("in_progress")
    await poster.flush()
    recorder.meters.add_tts("elevenlabs", "eleven_flash_v2_5", 5)
    await poster.flush()
    batches = posted(route)
    assert [e["type"] for e in batches[0]] == ["status", "usage"]
    assert batches[1][0]["usage"]["tts"][0]["characters"] == 15  # type: ignore[index]
    assert poster.posts == 2


@respx.mock
async def test_empty_batch_is_a_pure_heartbeat() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=OK))
    _, poster, _ = make()
    await poster.flush(with_usage=False)
    assert posted(route) == [[]]


@respx.mock
async def test_end_call_control_triggers_hang_up_once() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=END))
    _, poster, reasons = make()
    await poster.flush()
    await poster.flush()
    assert reasons == ["insufficient_credit"]
    assert poster.end_call_requested == "insufficient_credit"


@respx.mock
async def test_409_stops_posting() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(409, json={"detail": "terminal"}))
    _, poster, _ = make()
    await poster.flush()
    assert poster.closed
    await poster.flush()
    assert route.call_count == 1


@respx.mock
async def test_failed_post_requeues_events_with_same_seq() -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("x"), httpx.ConnectError("x"), httpx.Response(200, json=OK)]
    )
    recorder, poster, _ = make()
    recorder.status("in_progress")
    assert await poster.flush(with_usage=False) is None  # gave up after 2 attempts
    assert recorder.pending == 1
    await poster.flush(with_usage=False)
    assert posted(route)[-1][0]["seq"] == 1
    assert recorder.pending == 0


@respx.mock
async def test_large_queues_post_in_batches_of_200() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=OK))
    recorder, poster, _ = make()
    for _ in range(450):
        recorder.warning("vendor_retry")
    await poster.flush()
    sizes = [len(b) for b in posted(route)]
    assert sizes == [200, 200, 51]


@respx.mock
async def test_periodic_heartbeat_and_final_flush_on_stop() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=OK))
    recorder, poster, _ = make(interval_s=0.01)
    poster.start()
    await asyncio.sleep(0.05)
    recorder.status("ended", disconnect_reason="user_hangup")
    await poster.stop()
    assert route.call_count >= 3
    assert posted(route)[-1][0]["status"] == "ended"
