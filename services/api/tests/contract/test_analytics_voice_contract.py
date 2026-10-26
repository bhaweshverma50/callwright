"""Contract tests for the analytics assistant and the voice copilot (006 T057, T072)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import FastAPI

from tests.calls_support import SeededCalls
from tests.contract.conftest import check


async def _clear_limits(app: FastAPI) -> None:
    for pattern in ("rl:analytics_chat:*", "rl:voice_*"):
        async for key in app.state.redis.scan_iter(pattern):
            await app.state.redis.delete(key)


async def test_analytics_chat_and_catalog(
    client: httpx.AsyncClient, seeded_calls: SeededCalls, app: FastAPI
) -> None:
    await _clear_limits(app)
    h = seeded_calls.a.headers
    catalog = check(await client.get("/v1/analytics/catalog", headers=h))
    assert catalog.status_code == 200 and catalog.json()["suggested_questions"]
    for q in (
        "Cost by agent this month",
        "Busiest day last week",
        "Total calls this month",
        "What is our churn rate?",
    ):
        body = {"messages": [{"role": "user", "content": q}], "timezone": "Asia/Kolkata"}
        r = check(
            await client.post(
                "/v1/analytics/chat", json=body, headers={**h, "Idempotency-Key": uuid.uuid4().hex}
            )
        )
        assert r.status_code == 200
    bad = {"messages": [{"role": "assistant", "content": "hi"}], "timezone": "UTC"}
    assert (
        check(
            await client.post("/v1/analytics/chat", json=bad, headers={**h, "Idempotency-Key": "k-1"})
        ).status_code
        == 422
    )
    unauth = await client.post("/v1/analytics/chat", json=bad, headers={"Idempotency-Key": "k-2"})
    assert check(unauth).status_code == 401


def _state(**extra: Any) -> dict[str, Any]:
    return {
        "current_route": "/dashboard",
        "page_title": "Dashboard",
        "current_datetime": "2026-10-16T10:00:00Z",
        "timezone": "UTC",
        "available_actions": [{"key": "refresh_dashboard", "label": "Refresh the dashboard"}],
        "highlightable_elements": ["period_picker"],
        **extra,
    }


async def test_voice_commands(client: httpx.AsyncClient, seeded_calls: SeededCalls, app: FastAPI) -> None:
    await _clear_limits(app)
    h = seeded_calls.a.headers
    token = check(await client.post("/v1/voice-commands/stream-token", headers=h))
    assert token.status_code == 503  # no vendor key: the browser records and uploads instead
    clip = check(
        await client.post(
            "/v1/voice-commands/transcribe",
            files={"audio": ("clip.txt", b"show me failed calls from yesterday", "text/plain")},
            headers=h,
        )
    )
    assert clip.json() == {"transcript": "show me failed calls from yesterday"}
    big = await client.post(
        "/v1/voice-commands/transcribe",
        files={"audio": ("clip.webm", b"0" * (2 * 1024 * 1024 + 1), "audio/webm")},
        headers=h,
    )
    assert check(big).status_code == 413
    for transcript in (
        "show me failed calls from yesterday",
        "refresh the dashboard",
        "delete this agent",
        "what page am I on",
    ):
        r = check(
            await client.post(
                "/v1/voice-commands/interpret",
                json={"transcript": transcript, "visual_state": _state()},
                headers=h,
            )
        )
        assert r.status_code == 200
    nav = (
        await client.post(
            "/v1/voice-commands/interpret",
            json={"transcript": "show me failed calls from yesterday", "visual_state": _state()},
            headers=h,
        )
    ).json()
    assert (
        nav["action"] == "navigate"
        and nav["target"] == "/calls"
        and nav["params"] == {"status": ["failed"], "date_range": "yesterday"}
    )
    assert (
        check(
            await client.post("/v1/voice-commands/interpret", json={"transcript": ""}, headers=h)
        ).status_code
        == 422
    )


async def test_stream_token_with_vendor(
    client: httpx.AsyncClient, seeded_calls: SeededCalls, app: FastAPI
) -> None:
    class Vendor:
        name = "deepgram"

        async def mint_stream_credential(self, ttl_s: int) -> dict[str, Any]:
            assert ttl_s <= 60
            return {
                "provider": "deepgram",
                "stream_url": "wss://api.deepgram.com/v1/listen?model=nova-3",
                "auth_scheme": "websocket_subprotocol_token",
                "token": "tmp-token",
                "expires_at": "2026-10-16T10:01:00+00:00",
                "encoding": "webm_opus",
                "sample_rate_hz": None,
                "language": "en",
            }

        async def transcribe(self, audio: bytes, mime: str) -> str:
            return ""

    await _clear_limits(app)
    app.state.copilot_stt = Vendor()
    try:
        r = check(await client.post("/v1/voice-commands/stream-token", headers=seeded_calls.a.headers))
    finally:
        app.state.copilot_stt = None
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
