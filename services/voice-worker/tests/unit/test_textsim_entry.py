"""The textsim process (008 T005, T019): arq options, job functions and the health listener."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from worker.settings import WorkerSettings
from worker.textsim import QUEUE_NAME, entry, runner


def settings(**env: str) -> WorkerSettings:
    return WorkerSettings.model_validate(env)


def test_settings_defaults() -> None:
    s = settings()
    assert s.redis_url == "redis://localhost:56379/0"
    assert s.textsim_max_jobs == 10 and s.textsim_job_timeout_s == 900


def test_worker_options() -> None:
    s = settings(
        WORKER_ROLE="textsim",
        REDIS_URL="redis://:p%40ss@10.0.0.5:6379/2",
        TEXTSIM_MAX_JOBS="4",
    )
    options = entry.worker_options(s)
    assert options["queue_name"] == QUEUE_NAME == "arq:textsim"
    assert [f.__name__ for f in options["functions"]] == ["run_single_turn", "run_simulation"]
    assert options["max_jobs"] == 4 and options["job_timeout"] == 900
    redis = options["redis_settings"]
    assert (redis.host, redis.port, redis.database, redis.password) == ("10.0.0.5", 6379, 2, "p@ss")


async def test_jobs_delegate_to_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, ...]] = []

    async def single(api: Any, trn: str, tc: str, deps: Any) -> str:
        seen.append(("single", api, trn, tc, deps))
        return "completed"

    async def simulation(api: Any, srun: str, deps: Any) -> str:
        seen.append(("sim", api, srun, deps))
        return "failed"

    monkeypatch.setattr(runner, "run_single_turn", single)
    monkeypatch.setattr(runner, "run_simulation", simulation)
    ctx = {"api": "api", "deps": "deps"}
    assert await entry.run_single_turn(ctx, "trn_1", "tc_1") == "completed"
    assert await entry.run_simulation(ctx, "srun_1") == "failed"
    assert seen == [("single", "api", "trn_1", "tc_1", "deps"), ("sim", "api", "srun_1", "deps")]


async def test_context_and_health_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings(WORKER_HEALTH_PORT="0")
    monkeypatch.setattr(entry, "get_settings", lambda: s)
    ctx: dict[str, Any] = {}
    await entry.startup(ctx)
    try:
        assert ctx["deps"].internal_api_url == s.internal_api_url
        assert ctx["deps"].heartbeat_interval_s == s.heartbeat_interval_s
        port = ctx["health"].sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\n\r\n")
        await writer.drain()
        reply = await reader.read()
        writer.close()
        assert reply.startswith(b"HTTP/1.1 200 OK") and reply.endswith(b"ok")
    finally:
        await entry.shutdown(ctx)
