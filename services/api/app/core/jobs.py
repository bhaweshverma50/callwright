"""arq jobs worker (T014). Run with ``uv run arq app.core.jobs.WorkerSettings``.

Features register job functions and cron entries here; the worker builds one ``Database`` and
one Redis client at startup and passes them through ``ctx``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.cron import CronJob

from app.core.config import get_settings
from app.core.db import Database
from app.core.logging import configure_logging


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    ctx["settings"] = settings
    ctx["db"] = Database(settings.database_url, settings.database_admin_url, pool_size=4)


async def shutdown(ctx: dict[str, Any]) -> None:
    db: Database | None = ctx.get("db")
    if db is not None:
        await db.dispose()


async def enqueue(job_name: str, *args: Any, **kwargs: Any) -> None:
    pool: ArqRedis = await create_pool(redis_settings())
    try:
        await pool.enqueue_job(job_name, *args, **kwargs)
    finally:
        await pool.aclose()


def _functions() -> list[Any]:
    from app.billing.jobs import reconcile_balances

    return [reconcile_balances]


def _crons() -> list[CronJob]:
    from app.billing.jobs import reconcile_balances

    return [cron(reconcile_balances, hour={3}, minute={0}, run_at_startup=False)]


class WorkerSettings:
    functions: ClassVar[list[Any]] = _functions()
    cron_jobs: ClassVar[list[CronJob]] = _crons()
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
