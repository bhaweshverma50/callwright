"""The arq jobs worker (T014): every feature's jobs and crons from ``app/features.py``, installed
the same way as in the API.

``python -m app.worker`` (the container's ``worker`` role) runs it with a health listener on
``$PORT`` (default 8080); ``uv run arq app.worker.WorkerSettings`` runs it alone. SIGTERM and
SIGINT stop the worker the way the arq CLI does; when the worker loop dies with an error the
process exits non-zero so the platform restarts the container.

``python -m app.worker replay <call_id>`` re-runs one call's post-call pipeline (003 quickstart
section 6).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any, ClassVar, cast

import httpx
from arq.cron import CronJob
from arq.typing import WorkerCoroutine
from arq.worker import Function, create_worker, func
from callwright_contract.adapters import load_catalog

from app import features
from app.calls.jobs import run_pipeline_for
from app.calls.lookups import workspace_for_call
from app.channels.sip import build_sip
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import ProblemError
from app.core.feature import Runtime
from app.core.livekit import build_livekit
from app.core.logging import configure_logging
from app.core.queue import ArqJobQueue, redis_settings_for
from app.core.worker_health import serve_health

logger = logging.getLogger("app.worker")


def _configure_logging(settings: Settings) -> None:
    configure_logging(settings.log_level, settings.log_json, features.secret_fields())


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    _configure_logging(settings)
    ctx["settings"] = settings
    ctx["db"] = Database(settings.database_url, settings.database_admin_url, pool_size=4)
    ctx["jobs"] = ArqJobQueue(pool=ctx["redis"])
    ctx["livekit"] = build_livekit(settings)
    ctx["sip"] = build_sip(settings)
    ctx["adapter_catalog"] = load_catalog()
    ctx["http"] = httpx.AsyncClient(follow_redirects=False)
    await features.install(Runtime("worker", settings, ctx["db"], ctx["jobs"], ctx["http"]))


async def shutdown(ctx: dict[str, Any]) -> None:
    for key in ("http", "livekit", "sip"):
        client = ctx.get(key)
        if client is not None:
            await client.aclose()
    db: Database | None = ctx.get("db")
    if db is not None:
        await db.dispose()


def job_functions() -> list[Function]:
    """Each job under the name callers enqueue it by."""
    return [func(cast(WorkerCoroutine, fn), name=name) for name, fn in features.job_functions().items()]


class WorkerSettings:
    functions: ClassVar[list[Function]] = job_functions()
    cron_jobs: ClassVar[list[CronJob]] = features.crons()
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings_for(get_settings().redis_url)
    poll_delay = get_settings().arq_poll_delay_s


async def run(port: int) -> None:
    _configure_logging(get_settings())
    # Registers SIGINT/SIGTERM handlers on this loop, like the arq CLI.
    worker = create_worker(WorkerSettings)  # type: ignore[arg-type]
    server = await serve_health(worker, "0.0.0.0", port)  # noqa: S104 (container listener)
    logger.info("worker health endpoint listening on :%s", port)
    try:
        await worker.async_run()
    except asyncio.CancelledError:
        logger.info("worker stopped")
    finally:
        server.close()
        await server.wait_closed()
        await worker.close()


async def replay(call_id: str) -> int:
    settings = get_settings()
    db = Database(settings.database_url, settings.database_admin_url, pool_size=2)
    queue = ArqJobQueue()
    http = httpx.AsyncClient(follow_redirects=False)
    try:
        await features.install(Runtime("worker", settings, db, queue, http))
        try:
            workspace_id = await workspace_for_call(db, call_id)
        except ProblemError:
            print(f"no call {call_id}", file=sys.stderr)
            return 1
        result = await run_pipeline_for(
            db,
            queue,
            workspace_id,
            call_id,
            catalog=load_catalog(),
            recordings_bucket=settings.recordings_bucket,
            replay=True,
        )
        print(f"{call_id}: {result.status} {result.steps}")
        return 0 if result.status in ("finished", "not_ready") else 2
    finally:
        await http.aclose()
        await queue.aclose()
        await db.dispose()


def main(argv: list[str]) -> int:
    if not argv:
        asyncio.run(run(int(os.environ.get("PORT", "8080"))))
        return 0
    if len(argv) == 2 and argv[0] == "replay":
        return asyncio.run(replay(argv[1]))
    print("usage: python -m app.worker [replay <call_id>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
