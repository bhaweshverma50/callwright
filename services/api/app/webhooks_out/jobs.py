"""Webhook delivery job and 30-day purge (003 T091, research R15, FR-038, FR-039, FR-040).

One attempt per job run. The URL is checked (and pinned) at send time; a blocked URL ends the
delivery as ``blocked``. Any 2xx within the timeout succeeds. Timeouts, connection errors, 408,
429 and 5xx are retried after about 10 s, 1 min, 5 min, 30 min and 2 h (plus or minus 10%), so
a delivery has at most six attempts; any other status fails at once.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select, text

from app.calls.effects import DELIVER_WEBHOOK
from app.core.config import Settings
from app.core.db import Database
from app.core.queue import JobQueue
from app.core.secrets import KeyWrapper
from app.core.url_guard import Resolver, UrlNotAllowed, check_url, guarded_request
from app.webhooks_out import service, signing
from app.webhooks_out.models import WebhookDelivery

logger = logging.getLogger(__name__)

RETRY_SCHEDULE_S: tuple[int, ...] = (10, 60, 300, 1800, 7200)
MAX_ATTEMPTS = len(RETRY_SCHEDULE_S) + 1
RETRYABLE_STATUS = frozenset({408, 429})
EXCERPT_CHARS = 1024
USER_AGENT = "Callwright-Webhooks/1"
PURGE_DAYS = 30
FINAL = frozenset({"succeeded", "failed", "blocked"})


def retry_delay(attempt: int, rng: random.Random | None = None) -> float:
    """Delay before the next attempt after attempt number ``attempt`` (1-based), +-10% jitter."""
    base = RETRY_SCHEDULE_S[min(attempt, len(RETRY_SCHEDULE_S)) - 1]
    return float(base * (rng or random).uniform(0.9, 1.1))


def is_retryable(status_code: int | None, error: str | None) -> bool:
    if error in ("timeout", "connection_error"):
        return True
    return status_code is not None and (status_code in RETRYABLE_STATUS or 500 <= status_code <= 599)


@dataclass(frozen=True)
class AttemptResult:
    status_code: int | None
    duration_ms: int | None
    error: str | None
    response_excerpt: str | None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code <= 299


def headers_for(
    row_id: str, event: str, body: bytes, secrets: Sequence[str], timestamp: int
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Callwright-Event": event,
        "Callwright-Delivery": row_id,
        signing.HEADER: signing.sign(body, secrets, timestamp),
    }


async def send_once(
    client: httpx.AsyncClient,
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout_ms: int,
    *,
    allow_http: bool,
    allow_private: bool,
    resolver: Resolver | None = None,
) -> AttemptResult:
    try:
        checked = await check_url(url, allow_http=allow_http, allow_private=allow_private, resolver=resolver)
    except UrlNotAllowed as exc:
        return AttemptResult(None, None, "url_not_allowed", exc.detail[:EXCERPT_CHARS])
    started = time.monotonic()
    try:
        response = await guarded_request(
            client, "POST", checked, content=body, headers=headers, timeout=timeout_ms / 1000
        )
    except httpx.TimeoutException:
        return AttemptResult(None, round((time.monotonic() - started) * 1000), "timeout", None)
    except httpx.TransportError as exc:
        logger.info("webhook connection error to %s: %s", checked.host, exc)
        return AttemptResult(None, round((time.monotonic() - started) * 1000), "connection_error", None)
    duration = round((time.monotonic() - started) * 1000)
    if duration > timeout_ms:
        return AttemptResult(response.status_code, duration, "timeout", response.text[:EXCERPT_CHARS])
    return AttemptResult(response.status_code, duration, None, response.text[:EXCERPT_CHARS])


def attempt_json(n: int, at: datetime, result: AttemptResult) -> dict[str, Any]:
    return {
        "n": n,
        "at": at.isoformat(),
        "status_code": result.status_code,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "response_excerpt": result.response_excerpt,
    }


@dataclass
class DeliveryOutcome:
    status: str
    attempt: dict[str, Any] | None = None
    retry_in_s: float | None = None


async def deliver(
    db: Database,
    settings: Settings,
    client: httpx.AsyncClient,
    queue: JobQueue | None,
    workspace_id: str,
    delivery_id: str,
    *,
    wrapper: KeyWrapper | None = None,
    resolver: Resolver | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> DeliveryOutcome:
    wrapper = wrapper or service.key_wrapper(settings)
    async with db.transaction(workspace_id=workspace_id) as session:
        row = (
            await session.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.id == delivery_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return DeliveryOutcome("busy")
        if row.status in FINAL or len(row.attempts or []) >= MAX_ATTEMPTS:
            return DeliveryOutcome(row.status)
        row.status = "delivering"
        secrets = await service.signing_secrets(session, wrapper, workspace_id, now)
        url, event, body, timeout_ms = row.url, row.event, row.body.encode(), row.timeout_ms
        n = len(row.attempts or []) + 1
    stamp = now or datetime.now(UTC)
    headers = headers_for(delivery_id, event, body, secrets, int(stamp.timestamp()))
    result = await send_once(
        client,
        url,
        body,
        headers,
        timeout_ms,
        allow_http=settings.webhooks_allow_http,
        allow_private=settings.webhooks_allow_private,
        resolver=resolver,
    )
    attempt = attempt_json(n, stamp, result)
    outcome = DeliveryOutcome("pending", attempt)
    async with db.transaction(workspace_id=workspace_id) as session:
        row = (
            await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update()
            )
        ).scalar_one()
        row.attempts = [*(row.attempts or []), attempt]
        if result.succeeded:
            row.status, row.next_attempt_at, row.completed_at = "succeeded", None, stamp
        elif result.error == "url_not_allowed":
            row.status, row.next_attempt_at, row.completed_at = "blocked", None, stamp
        elif is_retryable(result.status_code, result.error) and n < MAX_ATTEMPTS:
            outcome.retry_in_s = retry_delay(n, rng)
            row.status = "pending"
            row.next_attempt_at = stamp + timedelta(seconds=outcome.retry_in_s)
        else:
            row.status, row.next_attempt_at, row.completed_at = "failed", None, stamp
        outcome.status = row.status
    if outcome.retry_in_s is not None and queue is not None:
        await queue.enqueue(
            DELIVER_WEBHOOK,
            workspace_id,
            delivery_id,
            defer_by_s=outcome.retry_in_s,
            job_id=f"{delivery_id}:{n + 1}",
        )
    return outcome


async def deliver_webhook(ctx: dict[str, Any], workspace_id: str, delivery_id: str) -> str:
    outcome = await deliver(
        ctx["db"], ctx["settings"], ctx["http"], ctx.get("jobs"), workspace_id, delivery_id
    )
    return outcome.status


async def purge_webhook_deliveries(ctx: dict[str, Any]) -> int:
    """Daily: drop deliveries older than 30 days and expired idempotency keys."""
    db: Database = ctx["db"]
    async with db.transaction() as session:
        purged = int(
            (
                await session.execute(text("select webhook_deliveries_purge(:d)"), {"d": PURGE_DAYS})
            ).scalar_one()
        )
        await session.execute(text("select idempotency_keys_purge()"))
    return purged
