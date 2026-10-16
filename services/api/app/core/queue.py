"""Job queue port (003): where request handlers and jobs enqueue follow-up work.

Kept apart from ``app.core.jobs`` (the arq worker definition imports every feature's jobs), so
feature modules can depend on the queue without import cycles.
"""

from __future__ import annotations

from typing import Any, Protocol

from arq.connections import ArqRedis, RedisSettings, create_pool


def _default_settings() -> RedisSettings:
    from app.core.config import get_settings

    return RedisSettings.from_dsn(get_settings().redis_url)


class JobQueue(Protocol):
    """Where request handlers and jobs enqueue work (``app.state.jobs``, ``ctx["jobs"]``)."""

    async def enqueue(
        self, name: str, *args: Any, defer_by_s: float | None = None, job_id: str | None = None
    ) -> None: ...


class ArqJobQueue:
    """``JobQueue`` over one shared arq pool, created on first use."""

    def __init__(self, settings: RedisSettings | None = None, pool: ArqRedis | None = None) -> None:
        self._settings = settings
        self._pool = pool
        self._owns_pool = pool is None

    async def _get(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(self._settings or _default_settings())
        return self._pool

    async def enqueue(
        self, name: str, *args: Any, defer_by_s: float | None = None, job_id: str | None = None
    ) -> None:
        pool = await self._get()
        await pool.enqueue_job(name, *args, _defer_by=defer_by_s, _job_id=job_id)

    async def aclose(self) -> None:
        if self._pool is not None and self._owns_pool:
            await self._pool.aclose()
        self._pool = None
