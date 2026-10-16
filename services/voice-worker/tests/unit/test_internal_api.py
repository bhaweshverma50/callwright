"""Typed internal API client against the 003 contracts (respx, no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from tests.harness.runner import CALL_ID as HARNESS_CALL_ID
from worker.internal_api import (
    CallClosed,
    ClaimRejected,
    ClaimRequest,
    InternalApiClient,
    InternalApiError,
    SipAttributes,
)

BASE = "http://api.test/v1/internal"
CALL_ID = HARNESS_CALL_ID
RUNTIME: dict[str, Any] = {
    "channel": "web",
    "direction": "inbound",
    "agent_id": "agt_1",
    "agent_version_id": "agv_1",
    "agent_type": "single_prompt",
    "config": {"language": "en-US"},
    "variables": {"customer_name": "Priya"},
    "limits": {"end_on_silence_s": 30, "max_duration_s": 600, "ring_duration_ms": 0},
    "background_audio_url": None,
    "caller_join_timeout_s": 60,
    "outbound_dial": None,
    "heartbeat_interval_s": 10,
    "recording_enabled": False,
    "stt_resolved_model": "nova-3",
    "controls": [{"path": "tts.speed", "min": 0.5, "max": 2.0, "step": 0.1}],
}


async def no_sleep(_: float) -> None:
    return None


def client(**kw: Any) -> InternalApiClient:
    return InternalApiClient(BASE, "svc-token", sleep=no_sleep, **kw)


@respx.mock
async def test_claim_request_and_response_shapes() -> None:
    route = respx.post(f"{BASE}/calls/claim").mock(
        return_value=httpx.Response(
            200, json={"admitted": True, "call_id": CALL_ID, "runtime": RUNTIME}
        )
    )
    api = client()
    resp = await api.claim(
        ClaimRequest(
            job_id="AJ_1",
            room_name="call-x",
            worker_id="AW_1",
            dispatch_metadata={"channel": "sip_inbound", "route_ref": "r1"},
            sip=SipAttributes(call_id="SCL_1", trunk_phone_number="+15550100"),
        )
    )
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer svc-token"
    assert json.loads(request.content) == {
        "job_id": "AJ_1",
        "room_name": "call-x",
        "worker_id": "AW_1",
        "dispatch_metadata": {"channel": "sip_inbound", "route_ref": "r1"},
        "sip": {"call_id": "SCL_1", "trunk_phone_number": "+15550100"},
    }
    assert resp.admitted and resp.runtime is not None
    assert resp.runtime.limits.end_on_silence_s == 30
    assert resp.runtime.stt_resolved_model == "nova-3"
    assert resp.runtime.controls is not None and resp.runtime.controls[0].max == 2.0
    assert resp.runtime.recording_enabled is False
    await api.aclose()


@respx.mock
async def test_claim_refusal() -> None:
    respx.post(f"{BASE}/calls/claim").mock(
        return_value=httpx.Response(
            200,
            json={
                "admitted": False,
                "call_id": CALL_ID,
                "refusal": {"disconnect_reason": "concurrency_limit"},
            },
        )
    )
    resp = await client().claim(
        ClaimRequest(job_id="j", room_name="r", worker_id="w", dispatch_metadata={})
    )
    assert not resp.admitted and resp.runtime is None
    assert resp.refusal is not None and resp.refusal.disconnect_reason == "concurrency_limit"


@pytest.mark.parametrize("status", [404, 409])
@respx.mock
async def test_claim_rejected(status: int) -> None:
    respx.post(f"{BASE}/calls/claim").mock(
        return_value=httpx.Response(
            status, json={"type": "about:blank", "title": "x", "status": status, "detail": "nope"}
        )
    )
    with pytest.raises(ClaimRejected) as exc:
        await client().claim(
            ClaimRequest(job_id="j", room_name="r", worker_id="w", dispatch_metadata={})
        )
    assert exc.value.status_code == status and exc.value.detail == "nope"


@respx.mock
async def test_retries_transient_failures_then_succeeds() -> None:
    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        side_effect=[
            httpx.ConnectError("down"),
            httpx.Response(503),
            httpx.Response(
                200, json={"accepted": 1, "duplicates": 0, "control": {"action": "none"}}
            ),
        ]
    )
    result = await client().post_events(CALL_ID, [{"seq": 1, "type": "usage", "usage": {}}])
    assert route.call_count == 3
    assert result.accepted == 1 and result.control.action == "none"


@respx.mock
async def test_gives_up_after_max_attempts() -> None:
    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(return_value=httpx.Response(502))
    with pytest.raises(InternalApiError):
        await client(max_attempts=3).post_events(CALL_ID, [])
    assert route.call_count == 3


@respx.mock
async def test_events_body_and_end_call_control() -> None:
    route = respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "accepted": 0,
                "duplicates": 2,
                "control": {"action": "end_call", "disconnect_reason": "insufficient_credit"},
            },
        )
    )
    events = [{"seq": 1, "type": "status", "status": "in_progress"}]
    result = await client().post_events(CALL_ID, events)
    assert json.loads(route.calls.last.request.content) == {"events": events}
    assert result.duplicates == 2
    assert result.control.action == "end_call"
    assert result.control.disconnect_reason == "insufficient_credit"


@respx.mock
async def test_events_409_means_call_closed_and_422_is_an_error() -> None:
    respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        side_effect=[httpx.Response(409, json={"detail": "terminal"}), httpx.Response(422)]
    )
    with pytest.raises(CallClosed):
        await client().post_events(CALL_ID, [])
    with pytest.raises(InternalApiError) as exc:
        await client().post_events(CALL_ID, [])
    assert exc.value.status_code == 422


async def test_batch_limit() -> None:
    with pytest.raises(ValueError):
        await client().post_events(CALL_ID, [{"seq": i} for i in range(201)])


def test_backoff_is_exponential_with_jitter() -> None:
    api = InternalApiClient(BASE, "t", backoff_base_s=0.5, backoff_max_s=4)
    for attempt, nominal in [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (6, 4.0)]:
        delay = api.backoff_delay(attempt)
        assert nominal * 0.9 <= delay <= nominal * 1.1
