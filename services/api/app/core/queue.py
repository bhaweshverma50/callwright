"""Job queue port (003): where request handlers and jobs enqueue follow-up work.

Kept apart from ``app.core.jobs`` (the arq worker definition imports every feature's jobs), so
feature modules can depend on the queue without import cycles.
"""

from __future__ import annotations

from typing import Any, Protocol

from arq.connections import ArqRedis, RedisSettings, create_pool


def redis_settings_for(url: str, *, conn_timeout: float = 1.0, conn_retries: int = 5) -> RedisSettings:
    """arq connection settings from a ``redis://`` or ``rediss://`` (TLS) URL. TLS verifies the
    server certificate and host name against the system CAs; ``?ssl_cert_reqs=none`` turns
    verification off (self-signed test servers only)."""
    from urllib.parse import parse_qs, urlparse

    settings = RedisSettings.from_dsn(url)
    settings.conn_timeout = max(1, round(conn_timeout))
    settings.conn_retries = conn_retries
    if settings.ssl:
        query = parse_qs(urlparse(url).query)
        reqs = (query.get("ssl_cert_reqs") or ["required"])[0].lower()
        settings.ssl_cert_reqs = reqs
        settings.ssl_check_hostname = reqs == "required"
    return settings


def _default_settings() -> RedisSettings:
    from app.core.config import get_settings

    settings = get_settings()
    # Request handlers enqueue: fail fast so a stopped VM turns into a 503 waking_up quickly.
    return redis_settings_for(
        settings.redis_url, conn_timeout=settings.redis_connect_timeout_s, conn_retries=1
    )


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
