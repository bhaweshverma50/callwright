"""Wake the realtime VM on demand, and mark API activity for its idle detector.

Hosted topology: the API runs on Cloud Run (scales to zero) and Redis, LiveKit, the voice worker
and the jobs worker run on one Compute Engine VM that powers itself off after 15 idle minutes
(deploy/vm/idle-shutdown.sh). Two pieces live here:

* ``ActivityMarker``: ASGI middleware that writes ``cw:last_api_activity`` (unix seconds) to
  Redis at most once per 30 s per instance, skipping health checks, so the VM stays up while
  people use the app. Writes run in the background and never fail a request.
* ``VmWaker``: when Redis is unreachable (the VM is stopped), the API answers 503
  ``waking_up`` with ``Retry-After: 45`` and starts the VM through the Compute Engine API
  (``instances.start``) with the Cloud Run service account's token from the metadata server.
  Starts are debounced per instance, so a burst of requests sends one start call.
  Configured with WAKE_VM_PROJECT, WAKE_VM_ZONE and WAKE_VM_NAME; unset means no waking (local
  development), and the answer is a plain 503 ``dependency_unavailable``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import ProblemError, problem_response

logger = logging.getLogger("app.vm_waker")

ACTIVITY_KEY = "cw:last_api_activity"
ACTIVITY_INTERVAL_S = 30.0
ACTIVITY_TTL_S = 7 * 24 * 3600
WAKE_RETRY_AFTER_S = 45
WAKE_DEBOUNCE_S = 60.0
_METADATA = "http://metadata.google.internal/computeMetadata/v1"
METADATA_TOKEN_URL = f"{_METADATA}/instance/service-accounts/default/token"
COMPUTE_API = "https://compute.googleapis.com/compute/v1"
REDIS_DOWN_ERRORS: tuple[type[Exception], ...] = (RedisConnectionError, RedisTimeoutError)

Clock = Callable[[], float]


class VmWaker:
    """Starts one Compute Engine instance, at most once per debounce window per process."""

    def __init__(
        self,
        project: str | None,
        zone: str | None,
        name: str | None,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Clock = time.monotonic,
        debounce_s: float = WAKE_DEBOUNCE_S,
    ) -> None:
        self.project, self.zone, self.name = project, zone, name
        self._http = http
        self._clock = clock
        self._debounce_s = debounce_s
        self._last_start: float | None = None
        self._task: asyncio.Task[None] | None = None
        self.starts = 0

    @property
    def configured(self) -> bool:
        return bool(self.project and self.zone and self.name)

    def trigger(self) -> bool:
        """Schedule a start unless one is running or happened within the debounce window.
        Returns True when this call scheduled the start."""
        if not self.configured:
            return False
        now = self._clock()
        if self._task is not None and not self._task.done():
            return False
        if self._last_start is not None and now - self._last_start < self._debounce_s:
            return False
        self._last_start = now
        self._task = asyncio.get_running_loop().create_task(self._start())
        return True

    async def wait(self) -> None:
        """Wait for a scheduled start to finish (tests and shutdown)."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _start(self) -> None:
        client = self._http or httpx.AsyncClient(timeout=10.0)
        try:
            token = await client.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
            token.raise_for_status()
            access_token = token.json()["access_token"]
            url = f"{COMPUTE_API}/projects/{self.project}/zones/{self.zone}/instances/{self.name}/start"
            response = await client.post(url, headers={"Authorization": f"Bearer {access_token}"})
            self.starts += 1
            if response.status_code >= 400:
                logger.error("starting VM %s failed: %s %s", self.name, response.status_code, response.text)
            else:
                logger.warning("Redis unreachable: started VM %s (%s)", self.name, response.status_code)
        except (httpx.HTTPError, KeyError, ValueError):
            logger.exception("starting VM %s failed", self.name)
        finally:
            if self._http is None:
                await client.aclose()

    async def aclose(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


def waking_up() -> ProblemError:
    return ProblemError(
        503,
        "waking_up",
        "Starting the call servers",
        "Starting the call servers, this takes about a minute.",
        retry_after_s=WAKE_RETRY_AFTER_S,
        headers={"Retry-After": str(WAKE_RETRY_AFTER_S)},
    )


def dependency_unavailable() -> ProblemError:
    return ProblemError(
        503,
        "dependency_unavailable",
        "Service unavailable",
        "A backing service is unreachable. Try again shortly.",
        retry_after_s=5,
        headers={"Retry-After": "5"},
    )


async def redis_down_handler(request: Request, exc: Exception) -> JSONResponse:
    """Exception handler for Redis connection failures: wake the VM and answer 503."""
    waker: VmWaker | None = getattr(request.app.state, "vm_waker", None)
    if waker is not None and waker.configured:
        waker.trigger()
        logger.info("Redis unreachable (%s); asked the VM to start", type(exc).__name__)
        return problem_response(waking_up(), request)
    logger.warning("Redis unreachable (%s)", type(exc).__name__)
    return problem_response(dependency_unavailable(), request)


class ActivityMarker:
    """Pure ASGI middleware: records API use in Redis for the VM idle detector."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_getter: Callable[[], Any],
        skip_prefixes: tuple[str, ...] = ("/v1/health",),
        interval_s: float = ACTIVITY_INTERVAL_S,
        clock: Clock = time.monotonic,
        wall_clock: Clock = time.time,
    ) -> None:
        self.app = app
        self._redis_getter = redis_getter
        self._skip = skip_prefixes
        self._interval_s = interval_s
        self._clock = clock
        self._wall_clock = wall_clock
        self._last: float | None = None
        self._pending: set[asyncio.Task[None]] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not str(scope.get("path", "")).startswith(self._skip):
            self._maybe_mark()
        await self.app(scope, receive, send)

    def _maybe_mark(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval_s:
            return
        redis = self._redis_getter()
        if redis is None:
            return
        self._last = now
        task = asyncio.get_running_loop().create_task(self._mark(redis))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _mark(self, redis: Any) -> None:
        try:
            await redis.set(ACTIVITY_KEY, str(int(self._wall_clock())), ex=ACTIVITY_TTL_S)
        except Exception:  # never fail or slow a request over the marker; retried next interval
            logger.debug("activity marker write failed", exc_info=True)
