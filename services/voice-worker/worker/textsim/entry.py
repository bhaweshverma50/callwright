"""The ``textsim`` process (008 T019, research R1): an arq consumer on the platform Redis.

The contract's ``TEXTSIM_QUEUE``; the API enqueues exactly two jobs:

- ``run_single_turn(ctx, test_run_id, test_case_id)``
- ``run_simulation(ctx, simulation_run_id)``

The API gates per-workspace concurrency before it enqueues; this process only caps its own
parallel jobs (``TEXTSIM_MAX_JOBS``, default 10). Settings come from the environment like the
live role (``worker.settings``): ``REDIS_URL``, ``CALLWRIGHT_INTERNAL_API_URL``,
``CALLWRIGHT_SERVICE_TOKEN``, the LLM vendor keys (without a key for a provider its models run
on the offline scripts, ``worker.textsim.llm``) and ``CALLWRIGHT_OTEL_EXPORTER``. A small health
listener answers ``200 ok`` on ``WORKER_HEALTH_PORT`` for the image's health check.

Start with ``WORKER_ROLE=textsim python -m worker.entry`` (the image entry point) or
``python -m worker.textsim.entry``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from typing import Any

from arq.worker import func
from callwright_contract.values import RUN_SIMULATION, RUN_SINGLE_TURN, TEXTSIM_QUEUE

from worker import telemetry
from worker.adapters.registry import AdapterRegistry
from worker.internal_api import InternalApiClient
from worker.settings import WorkerSettings, get_settings
from worker.textsim import runner
from worker.textsim.llm import settings_factory

log = logging.getLogger("callwright.textsim")


async def run_single_turn(ctx: dict[str, Any], test_run_id: str, test_case_id: str) -> str:
    return await runner.run_single_turn(ctx["api"], test_run_id, test_case_id, ctx["deps"])


async def run_simulation(ctx: dict[str, Any], simulation_run_id: str) -> str:
    return await runner.run_simulation(ctx["api"], simulation_run_id, ctx["deps"])


def build_context(
    settings: WorkerSettings, registry: AdapterRegistry | None = None
) -> dict[str, Any]:
    """The per-process job context: the internal API client and the runner's models."""
    registry = registry or AdapterRegistry()
    deps = runner.RunnerDeps(
        models=settings_factory(settings, registry),
        registry=registry,
        heartbeat_interval_s=settings.heartbeat_interval_s,
    )
    return {"api": InternalApiClient.from_settings(settings), "deps": deps}


async def _health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(Exception):
        await asyncio.wait_for(reader.read(1024), timeout=2)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
    writer.close()


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    if not telemetry.enabled():
        telemetry.configure_tracing(settings.otel_exporter)
    ctx.update(build_context(settings))
    ctx["health"] = await asyncio.start_server(_health, "0.0.0.0", settings.health_port)
    log.info(
        "textsim consuming %s (max %d jobs), health on :%d",
        TEXTSIM_QUEUE,
        settings.textsim_max_jobs,
        settings.health_port,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    health = ctx.get("health")
    if health is not None:
        health.close()
        with contextlib.suppress(Exception):
            await health.wait_closed()
    if "api" in ctx:
        await ctx["api"].aclose()
    telemetry.flush()


def redis_settings(url: str) -> Any:
    """arq settings from ``REDIS_URL``; the password is URL-decoded (render-env.sh encodes it)."""
    from urllib.parse import unquote

    from arq.connections import RedisSettings

    parsed = RedisSettings.from_dsn(url)
    if parsed.password:
        parsed.password = unquote(parsed.password)
    return parsed


def worker_options(settings: WorkerSettings) -> dict[str, Any]:
    """Keyword arguments for ``arq.Worker``."""
    return {
        "functions": [
            func(run_single_turn, name=RUN_SINGLE_TURN),
            func(run_simulation, name=RUN_SIMULATION),
        ],
        "queue_name": TEXTSIM_QUEUE,
        "redis_settings": redis_settings(settings.redis_url),
        "max_jobs": settings.textsim_max_jobs,
        "job_timeout": settings.textsim_job_timeout_s,
        "max_tries": 3,
        "on_startup": startup,
        "on_shutdown": shutdown,
    }


def main() -> int:
    from arq import Worker

    logging.basicConfig(level=logging.INFO)
    Worker(**worker_options(get_settings())).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
