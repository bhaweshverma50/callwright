"""Job queue port (003): where request handlers and jobs enqueue follow-up work, by the job name
a feature's manifest declares (``Feature.jobs``; the worker is ``app.worker``).

Work that changes rows inside a transaction collects its follow-up jobs in ``Deferred``; the
caller enqueues them with ``dispatch`` only after the commit, so a job never runs against a row
that was rolled back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from arq.connections import ArqRedis, RedisSettings, create_pool

logger = logging.getLogger(__name__)


def redis_settings_for(url: str, *, conn_timeout: float = 1.0, conn_retries: int = 5) -> RedisSettings:
    """arq connection settings from a ``redis://`` or ``rediss://`` (TLS) URL. TLS verifies the
    server certificate and host name against the system CAs; ``?ssl_cert_reqs=none`` turns
    verification off (self-signed test servers only)."""
    from urllib.parse import parse_qs, unquote, urlparse

    settings = RedisSettings.from_dsn(url)
    # arq keeps the password percent-encoded; deploy/vm/render-env.sh encodes it into the URL.
    if settings.password:
        settings.password = unquote(settings.password)
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


@dataclass(frozen=True)
class Job:
    name: str
    args: tuple[Any, ...]
    defer_by_s: float | None = None
    job_id: str | None = None


@dataclass
class Deferred:
    jobs: list[Job] = field(default_factory=list)

    def add(self, name: str, *args: Any, defer_by_s: float | None = None, job_id: str | None = None) -> None:
        self.jobs.append(Job(name, tuple(args), defer_by_s, job_id))

    def extend(self, other: Deferred) -> None:
        self.jobs.extend(other.jobs)


async def dispatch(queue: JobQueue | None, deferred: Deferred) -> None:
    """Enqueue every collected job. A queue failure is logged: crons and replays recover."""
    if queue is None:
        return
    for job in deferred.jobs:
        try:
            await queue.enqueue(job.name, *job.args, defer_by_s=job.defer_by_s, job_id=job.job_id)
        except Exception:
            logger.exception("could not enqueue %s%s", job.name, job.args)
    deferred.jobs.clear()
