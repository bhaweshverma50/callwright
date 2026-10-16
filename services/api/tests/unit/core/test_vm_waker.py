"""Waking the realtime VM when Redis is away, and the API activity marker for its idle check."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from starlette.types import Receive, Scope, Send

from app.core.vm_waker import (
    ACTIVITY_KEY,
    COMPUTE_API,
    METADATA_TOKEN_URL,
    ActivityMarker,
    VmWaker,
)
from app.main import create_app
from tests.conftest import make_settings

START_URL = f"{COMPUTE_API}/projects/callwright-dev/zones/asia-south1-a/instances/callwright-rtc/start"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def compute_api(calls: list[httpx.Request], start_status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if str(request.url) == METADATA_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3599})
        if str(request.url) == START_URL:
            return httpx.Response(start_status, json={"kind": "compute#operation", "status": "RUNNING"})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def waker(calls: list[httpx.Request], clock: FakeClock | None = None, **kw: Any) -> VmWaker:
    return VmWaker(
        "callwright-dev",
        "asia-south1-a",
        "callwright-rtc",
        http=compute_api(calls, **kw),
        clock=clock or FakeClock(),
    )


async def test_start_uses_the_metadata_token_and_the_instances_start_api() -> None:
    calls: list[httpx.Request] = []
    w = waker(calls)
    assert w.trigger() is True
    await w.wait()
    token, start = calls
    assert token.headers["Metadata-Flavor"] == "Google"
    assert start.method == "POST" and str(start.url) == START_URL
    assert start.headers["Authorization"] == "Bearer ya29.token"
    assert w.starts == 1


async def test_concurrent_triggers_send_one_start_and_the_window_debounces() -> None:
    calls: list[httpx.Request] = []
    clock = FakeClock()
    w = waker(calls, clock)
    assert [w.trigger() for _ in range(10)].count(True) == 1
    await w.wait()
    clock.now += 30
    assert w.trigger() is False  # inside the 60 s window
    clock.now += 31
    assert w.trigger() is True
    await w.wait()
    assert w.starts == 2


async def test_a_failed_start_is_logged_not_raised() -> None:
    calls: list[httpx.Request] = []
    w = waker(calls, start_status=403)
    w.trigger()
    await w.wait()
    assert w.starts == 1


def test_unconfigured_waker_never_starts() -> None:
    w = VmWaker(None, "asia-south1-a", "callwright-rtc")
    assert not w.configured
    assert w.trigger() is False


def _redis_down_app(**settings: Any) -> Any:
    # Port 1 refuses connections at once: Redis is "down" like a stopped VM.
    return create_app(make_settings(redis_url="redis://127.0.0.1:1/0", **settings))


async def _sign_in(app: Any, n: int) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=app, client=("10.0.0.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        body = {"email": "a@example.com", "password": "correct-horse-9"}
        return list(await asyncio.gather(*(client.post("/v1/auth/sign-in", json=body) for _ in range(n))))


async def test_redis_down_answers_waking_up_and_starts_the_vm_once() -> None:
    app = _redis_down_app(
        wake_vm_project="callwright-dev", wake_vm_zone="asia-south1-a", wake_vm_name="callwright-rtc"
    )
    calls: list[httpx.Request] = []
    async with app.router.lifespan_context(app):
        app.state.vm_waker = waker(calls)
        responses = await _sign_in(app, 5)
        await app.state.vm_waker.wait()
    for r in responses:
        assert r.status_code == 503
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.headers["retry-after"] == "45"
        assert r.json()["code"] == "waking_up"
        assert r.json()["detail"] == "Starting the call servers, this takes about a minute."
    assert [str(c.url) for c in calls].count(START_URL) == 1


async def test_redis_down_without_a_vm_to_wake_is_a_plain_503() -> None:
    app = _redis_down_app()
    async with app.router.lifespan_context(app):
        (response,) = await _sign_in(app, 1)
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"


class FakeRedis:
    def __init__(self) -> None:
        self.sets: list[tuple[str, str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets.append((key, value, ex))


async def _ok(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_activity_marker_writes_at_most_every_30_seconds_and_skips_health() -> None:
    redis, clock = FakeRedis(), FakeClock()
    marker = ActivityMarker(
        _ok,
        redis_getter=lambda: redis,
        skip_prefixes=("/v1/health",),
        clock=clock,
        wall_clock=lambda: 1_700_000_000,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=marker), base_url="http://t") as client:
        await client.get("/v1/health")
        await asyncio.sleep(0)
        assert redis.sets == []
        await client.get("/v1/me")
        await client.get("/v1/agents")
        await asyncio.sleep(0)
        assert redis.sets == [(ACTIVITY_KEY, "1700000000", 7 * 24 * 3600)]
        clock.now += 30
        await client.get("/v1/agents")
        await asyncio.sleep(0)
        assert len(redis.sets) == 2


async def test_activity_marker_never_fails_a_request() -> None:
    class Broken:
        async def set(self, *a: Any, **k: Any) -> None:
            raise ConnectionError("down")

    marker = ActivityMarker(_ok, redis_getter=lambda: Broken())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=marker), base_url="http://t") as client:
        assert (await client.get("/v1/me")).status_code == 200
        await asyncio.sleep(0)
