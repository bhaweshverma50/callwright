"""How a call moves through its states (003 data-model section 1) and what each move sends.

Every path that rings, connects, ends, fails or completes a call (worker events, the stuck-call
reaper, LiveKit's ``room_finished``, room setup and claim failures, the post-call pipeline) goes
through these functions. Each move is the guarded ``transition()``: a call that already moved on
is a stale move, logged and skipped, so the first writer wins (disconnect reason included). A
call that closes sends ``call_ended`` (FR-035); one that connected also queues the pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.lookups import config_for
from app.calls.models import Call, billable_seconds, can_transition, transition
from app.calls.origins import policy
from app.core.queue import Deferred
from app.webhooks_out import service as webhooks

logger = logging.getLogger(__name__)

RUN_PIPELINE = "run_pipeline"
START_RECORDING = "start_recording"


def final_status(call: Call) -> str:
    return "voicemail" if call.disconnect_reason == "voicemail_reached" else "completed"


def _allowed(call: Call, new: str) -> bool:
    if can_transition(call.status, new):
        return True
    logger.info("stale status %s -> %s ignored for %s", call.status, new, call.id)
    return False


async def _move(session: AsyncSession, call: Call, new: str, **fields: Any) -> bool:
    if not _allowed(call, new):
        return False
    await session.flush()
    if not await transition(session, call.id, call.status, new, **fields):
        return False
    await session.refresh(call)
    return True


async def ring(session: AsyncSession, call: Call, at: datetime) -> bool:
    return await _move(session, call, "ringing", ringing_at=at)


async def connect(
    session: AsyncSession, call: Call, at: datetime, *, deferred: Deferred, now: datetime
) -> bool:
    if not await _move(session, call, "in_progress", connected_at=at):
        return False
    await notify(session, call, "call_started", deferred=deferred, now=now)
    return True


async def end_connected(
    session: AsyncSession,
    call: Call,
    *,
    at: datetime,
    reason: str,
    diagnostic: str | None,
    deferred: Deferred,
    now: datetime,
) -> bool:
    """End a connected call at ``at`` (never before it connected), billed to that second."""
    if not _allowed(call, "ended"):
        return False
    assert call.connected_at is not None
    ended_at = max(at, call.connected_at)
    if not await _move(
        session,
        call,
        "ended",
        ended_at=ended_at,
        disconnect_reason=reason,
        diagnostic=diagnostic,
        billable_seconds=billable_seconds(call.connected_at, ended_at),
    ):
        return False
    await notify(session, call, "call_ended", deferred=deferred, now=now)
    deferred.add(RUN_PIPELINE, call.workspace_id, call.id)
    return True


async def fail_unconnected(
    session: AsyncSession,
    call: Call,
    *,
    at: datetime,
    diagnostic: str | None,
    deferred: Deferred,
    now: datetime,
    status: str = "failed",
    reason: str | None = "error",
) -> bool:
    """Close a call that never connected (``failed``, ``no_answer`` or ``busy``): never billed."""
    fields: dict[str, Any] = {"ended_at": at, "billable_seconds": 0, "diagnostic": diagnostic}
    if status == "failed":
        fields["disconnect_reason"] = reason or "error"
    if not await _move(session, call, status, **fields):
        return False
    await notify(session, call, "call_ended", deferred=deferred, now=now)
    return True


async def finalize(session: AsyncSession, call: Call, now: datetime) -> None:
    """The pipeline's last step: ``completed`` or ``voicemail``, and the pipeline status."""
    if call.status == "processing":
        await _move(session, call, final_status(call), completed_at=now)
    if call.status in ("completed", "voicemail"):
        call.pipeline_status = "done_with_warnings" if call.pipeline_warnings else "done"


# Customer webhooks --------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def call_payload(call: Call, event: str, *, recording_url: str | None = None) -> dict[str, Any]:
    """Contract ``WebhookCall``. Transcript, analysis and cost are sent with ``call_analyzed``."""
    analyzed = event == "call_analyzed"
    status = call.status
    if analyzed and status == "processing":
        # Sent by the step just before ``complete``: report the status the call is about to get.
        status = final_status(call)
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


def _occurred_at(call: Call, event: str, now: datetime) -> datetime:
    if event == "call_started" and call.connected_at:
        return call.connected_at
    if event == "call_ended" and call.ended_at:
        return call.ended_at
    return now


async def notify(
    session: AsyncSession,
    call: Call,
    event: str,
    *,
    deferred: Deferred,
    recording_url: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Queue the customer webhook ``event`` for ``call`` once (the agent's ``webhook_url``).
    Returns the delivery id; None when there is no URL, the origin never reaches customers or the
    event was already queued."""
    if not policy(call.origin).reaches_customer:
        return None
    url, timeout_ms = webhooks.webhook_settings(await config_for(session, call))
    if url is None:
        return None
    now = now or datetime.now(UTC)
    body = webhooks.dumps(
        webhooks.envelope(
            event,
            f"evt_{call.id}_{event}",
            _occurred_at(call, event, now),
            call_payload(call, event, recording_url=recording_url),
        )
    )
    return await webhooks.enqueue_delivery(
        session, call.workspace_id, call.id, event, url, timeout_ms, body, deferred=deferred, now=now
    )
