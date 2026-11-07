"""Signing-secret lifecycle, event envelopes and idempotent delivery enqueue (003 T090, T093, T115).

* The workspace secret (``whsec_`` + 32 random bytes, base64url) is created lazily, stored
  encrypted in 001's ``secrets`` table and shown in full only by the rotate response. Rotation
  keeps the previous secret signing for 24 hours.
* ``enqueue_event`` writes one delivery per (call, event): the partial unique index on
  ``webhook_deliveries (call_id, event)`` makes a second enqueue a no-op, so replays and racing
  writers never send an event twice. The body is built once and reused byte for byte on every
  retry and redelivery; the signature and timestamp are fresh on each attempt.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.calls.effects import DELIVER_WEBHOOK, Deferred
from app.calls.models import Call
from app.core.ids import new_id
from app.core.secrets import KeyWrapper, WorkspaceSecret, get_secret, put_secret
from app.webhooks_out.models import WebhookDelivery, WebhookSigningSecret

ROTATION_OVERLAP = timedelta(hours=24)
DEFAULT_TIMEOUT_MS = 3000
MIN_TIMEOUT_MS = 1000
MAX_TIMEOUT_MS = 30000
RECORDING_URL_TTL_S = 600


def new_secret() -> str:
    return "whsec_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


# Signing secrets --------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretView:
    secret_last4: str
    created_at: datetime
    rotated_at: datetime | None
    previous_expires_at: datetime | None
    secret: str | None = None

    def masked(self) -> dict[str, Any]:
        return {
            "secret_last4": self.secret_last4,
            "created_at": self.created_at.isoformat(),
            "rotated_at": self.rotated_at.isoformat() if self.rotated_at else None,
            "previous_expires_at": self.previous_expires_at.isoformat() if self.previous_expires_at else None,
        }


async def _store_secret(session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, value: str) -> int:
    name = f"webhook_signing:{ULID()}"
    await put_secret(session, wrapper, workspace_id, name, value)
    row_id = (
        await session.execute(
            select(WorkspaceSecret.id).where(
                WorkspaceSecret.workspace_id == workspace_id, WorkspaceSecret.name == name
            )
        )
    ).scalar_one()
    return int(row_id)


async def _secret_value(session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, secret_id: int) -> str:
    name = (
        await session.execute(select(WorkspaceSecret.name).where(WorkspaceSecret.id == secret_id))
    ).scalar_one()
    value = await get_secret(session, wrapper, workspace_id, str(name))
    if value is None:  # pragma: no cover - the FK keeps the row
        raise LookupError(f"signing secret {secret_id} is missing")
    return value


async def ensure_secret(
    session: AsyncSession, wrapper: KeyWrapper, workspace_id: str
) -> tuple[WebhookSigningSecret, bool]:
    """The workspace's signing-secret row, created on first use. Returns (row, created)."""
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended('webhook_secret:' || :ws, 0))"),
        {"ws": workspace_id},
    )
    row = await session.get(WebhookSigningSecret, workspace_id)
    if row is not None:
        return row, False
    secret_id = await _store_secret(session, wrapper, workspace_id, new_secret())
    row = WebhookSigningSecret(workspace_id=workspace_id, current_secret_id=secret_id)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row, True


async def _view(
    session: AsyncSession, wrapper: KeyWrapper, row: WebhookSigningSecret, reveal: bool = False
) -> SecretView:
    value = await _secret_value(session, wrapper, row.workspace_id, row.current_secret_id)
    return SecretView(
        secret_last4=value[-4:],
        created_at=row.created_at,
        rotated_at=row.rotated_at,
        previous_expires_at=row.previous_expires_at,
        secret=value if reveal else None,
    )


async def masked_secret(session: AsyncSession, wrapper: KeyWrapper, workspace_id: str) -> SecretView:
    row, _ = await ensure_secret(session, wrapper, workspace_id)
    return await _view(session, wrapper, row)


async def rotate_secret(
    session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, now: datetime | None = None
) -> SecretView:
    """New current secret; the old one keeps signing until ``now + 24 h``. Shown in full once."""
    now = now or datetime.now(UTC)
    row, created = await ensure_secret(session, wrapper, workspace_id)
    if not created:
        row.previous_secret_id = row.current_secret_id
        row.previous_expires_at = now + ROTATION_OVERLAP
        row.current_secret_id = await _store_secret(session, wrapper, workspace_id, new_secret())
        row.rotated_at = now
        await session.flush()
    return await _view(session, wrapper, row, reveal=True)


async def signing_secrets(
    session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, now: datetime | None = None
) -> list[str]:
    """Secrets that sign a delivery now: current first, then the previous one inside the overlap."""
    now = now or datetime.now(UTC)
    row, _ = await ensure_secret(session, wrapper, workspace_id)
    out = [await _secret_value(session, wrapper, workspace_id, row.current_secret_id)]
    if row.previous_secret_id is not None and row.previous_expires_at and row.previous_expires_at > now:
        out.append(await _secret_value(session, wrapper, workspace_id, row.previous_secret_id))
    return out


# Envelopes --------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def webhook_settings(config: Mapping[str, Any] | None) -> tuple[str | None, int]:
    advanced = (config or {}).get("advanced") or {}
    url = advanced.get("webhook_url") if isinstance(advanced, Mapping) else None
    timeout = advanced.get("webhook_timeout_ms") if isinstance(advanced, Mapping) else None
    try:
        timeout_ms = int(timeout) if timeout is not None else DEFAULT_TIMEOUT_MS
    except (TypeError, ValueError):
        timeout_ms = DEFAULT_TIMEOUT_MS
    timeout_ms = min(MAX_TIMEOUT_MS, max(MIN_TIMEOUT_MS, timeout_ms))
    return (str(url) if isinstance(url, str) and url else None), timeout_ms


def call_payload(call: Call, event: str, *, recording_url: str | None = None) -> dict[str, Any]:
    """Contract ``WebhookCall``. Transcript, analysis and cost are sent with ``call_analyzed``."""
    analyzed = event == "call_analyzed"
    status = call.status
    if analyzed and status == "processing":
        # Sent by the step just before ``complete``: report the status the call is about to get.
        status = "voicemail" if call.disconnect_reason == "voicemail_reached" else "completed"
    payload: dict[str, Any] = {
        "call_id": call.id,
        "agent_id": call.agent_id,
        "agent_version_id": call.agent_version_id,
        "channel": call.channel,
        "direction": call.direction,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "status": status,
        "disconnect_reason": call.disconnect_reason,
        "created_at": _iso(call.created_at),
        "connected_at": _iso(call.connected_at),
        "ended_at": _iso(call.ended_at),
        "billable_seconds": call.billable_seconds,
        "dynamic_variables": {k: str(v) for k, v in (call.dynamic_variables or {}).items()},
        "metadata": dict(call.metadata_ or {}),
        "recording_enabled": call.recording_enabled,
        "recording_status": call.recording_status,
        "recording_url": None,
        "processing_warnings": list(call.pipeline_warnings or []),
    }
    if analyzed:
        payload.update(
            {
                "transcript": call.transcript or {"items": []},
                "summary": call.summary,
                "sentiment": call.sentiment,
                "analysis": call.analysis,
                "cost": call.cost_breakdown,
                "latency": call.latency_stats,
            }
        )
        if call.recording_status == "available" and call.recording_enabled:
            payload["recording_url"] = recording_url
    return payload


def envelope(event: str, event_id: str, occurred_at: datetime, call: dict[str, Any] | None) -> dict[str, Any]:
    return {"event": event, "event_id": event_id, "occurred_at": occurred_at.isoformat(), "call": call}


def dumps(body: Mapping[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False, default=str)


def _occurred_at(call: Call, event: str, now: datetime) -> datetime:
    if event == "call_started" and call.connected_at:
        return call.connected_at
    if event == "call_ended" and call.ended_at:
        return call.ended_at
    return now


async def enqueue_event(
    session: AsyncSession,
    call: Call,
    event: str,
    *,
    config: Mapping[str, Any] | None,
    deferred: Deferred,
    recording_url: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Queue ``event`` for ``call`` once. Returns the new delivery id (None: no URL or duplicate)."""
    url, timeout_ms = webhook_settings(config)
    if url is None or call.origin == "simulation":
        # 008: simulated calls never reach customer webhooks (FR-018).
        return None
    now = now or datetime.now(UTC)
    body = dumps(
        envelope(
            event,
            f"evt_{call.id}_{event}",
            _occurred_at(call, event, now),
            call_payload(call, event, recording_url=recording_url),
        )
    )
    delivery_id = new_id("whd")
    inserted = (
        await session.execute(
            text(
                "insert into webhook_deliveries (id, workspace_id, call_id, event, url, timeout_ms, body, "
                "next_attempt_at) values (:id, :ws, :call, :event, :url, :timeout, :body, :now) "
                "on conflict (call_id, event) where redelivery_of is null and event <> 'ping' do nothing "
                "returning id"
            ),
            {
                "id": delivery_id,
                "ws": call.workspace_id,
                "call": call.id,
                "event": event,
                "url": url[:2048],
                "timeout": timeout_ms,
                "body": body,
                "now": now,
            },
        )
    ).first()
    if inserted is None:
        return None
    deferred.add(DELIVER_WEBHOOK, call.workspace_id, delivery_id)
    return delivery_id


async def redeliver(
    session: AsyncSession, workspace_id: str, delivery_id: str, deferred: Deferred
) -> WebhookDelivery | None:
    """A new delivery of the same body (fresh signature and timestamp on send)."""
    original = (
        await session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_id, WebhookDelivery.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if original is None:
        return None
    copy = WebhookDelivery(
        id=new_id("whd"),
        workspace_id=workspace_id,
        call_id=original.call_id,
        event=original.event,
        url=original.url,
        timeout_ms=original.timeout_ms,
        body=original.body,
        status="pending",
        attempts=[],
        next_attempt_at=datetime.now(UTC),
        redelivery_of=original.redelivery_of or original.id,
    )
    session.add(copy)
    await session.flush()
    await session.refresh(copy)
    deferred.add(DELIVER_WEBHOOK, workspace_id, copy.id)
    return copy


def ping_body(delivery_id: str, now: datetime) -> str:
    return dumps(envelope("ping", f"evt_ping_{delivery_id}", now, None))


def delivery_json(row: WebhookDelivery, *, with_body: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "call_id": row.call_id,
        "event": row.event,
        "url": row.url,
        "status": row.status,
        "attempts": list(row.attempts or []),
        "next_attempt_at": _iso(row.next_attempt_at),
        "redelivery_of": row.redelivery_of,
        "created_at": _iso(row.created_at),
        "completed_at": _iso(row.completed_at),
    }
    if with_body:
        out["body"] = row.body
    return out
