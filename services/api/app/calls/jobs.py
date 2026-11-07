"""Call jobs: post-call pipeline and stuck-call reaper (003 T057, T080, T083; research R14, R16).

arq entry points take ``ctx`` with ``db``, ``settings``, ``livekit``, ``jobs`` and
``adapter_catalog`` (built in ``app.worker.startup``). The functions under them take explicit
arguments so tests run them without Redis.

Replay a call's pipeline (every step again; idempotent, so no second charge or notification)::

    uv run python -m app.worker replay <call_id>
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from callwright_contract import diagnostics as diag
from callwright_contract.adapters import AdapterCatalog
from sqlalchemy import select, text

from app.calls import lifecycle, pipeline
from app.calls.models import Call
from app.core.db import Database
from app.core.livekit import LiveKitError, LiveKitGateway
from app.core.queue import Deferred, JobQueue, dispatch

logger = logging.getLogger(__name__)

STUCK_QUEUED_S = 60
STUCK_HEARTBEAT_S = 60


async def run_pipeline_for(
    db: Database,
    queue: JobQueue | None,
    workspace_id: str,
    call_id: str,
    *,
    catalog: AdapterCatalog,
    recordings_bucket: str | None,
    replay: bool = False,
) -> pipeline.PipelineRun:
    result = await pipeline.run(
        db, workspace_id, call_id, catalog=catalog, recordings_bucket=recordings_bucket, replay=replay
    )
    await dispatch(queue, result.deferred)
    if result.status == "retry" and queue is not None:
        await queue.enqueue(lifecycle.RUN_PIPELINE, workspace_id, call_id, defer_by_s=result.retry_in_s)
    return result


async def run_pipeline(ctx: dict[str, Any], workspace_id: str, call_id: str) -> str:
    result = await run_pipeline_for(
        ctx["db"],
        ctx.get("jobs"),
        workspace_id,
        call_id,
        catalog=ctx["adapter_catalog"],
        recordings_bucket=ctx["settings"].recordings_bucket,
    )
    return result.status


@dataclass
class Reaped:
    call_id: str
    outcome: str
    room: str | None = None


@dataclass
class ReapResult:
    reaped: list[Reaped] = field(default_factory=list)
    deferred: Deferred = field(default_factory=Deferred)


async def reap_stuck(
    db: Database,
    *,
    queued_s: int = STUCK_QUEUED_S,
    heartbeat_s: int = STUCK_HEARTBEAT_S,
    now: datetime | None = None,
) -> ReapResult:
    """Close calls the runtime abandoned (FR-026). Queued past 60 s without a runtime becomes
    ``failed``; a connected call silent for 60 s becomes ``ended`` with ``error`` and is billed up
    to its last heartbeat."""
    now = now or datetime.now(UTC)
    out = ReapResult()
    async with db.transaction() as session:
        candidates = (
            await session.execute(
                text("select call_id, workspace_id, status from calls_stuck(:q, :h)"),
                {"q": queued_s, "h": heartbeat_s},
            )
        ).all()
    stale = now - timedelta(seconds=heartbeat_s)
    for row in candidates:
        async with db.transaction(workspace_id=row.workspace_id) as session:
            call = (
                await session.execute(select(Call).where(Call.id == row.call_id).with_for_update())
            ).scalar_one_or_none()
            if call is None:
                continue
            heartbeat = call.last_heartbeat_at
            if call.status == "queued":
                if call.created_at > now - timedelta(seconds=queued_s) or (heartbeat and heartbeat > stale):
                    continue
                diagnostic = (
                    diag.CALLER_NEVER_JOINED
                    if call.channel == "web" and call.claimed_at
                    else "worker_unavailable"
                )
                await lifecycle.fail_unconnected(
                    session, call, at=now, diagnostic=diagnostic, deferred=out.deferred, now=now
                )
            elif call.status == "ringing":
                if (heartbeat or call.claimed_at or call.created_at) > stale:
                    continue
                await lifecycle.fail_unconnected(
                    session, call, at=now, diagnostic="heartbeat_lost", deferred=out.deferred, now=now
                )
            elif call.status == "in_progress":
                if (heartbeat or call.claimed_at or call.created_at) > stale:
                    continue
                await lifecycle.end_connected(
                    session,
                    call,
                    at=heartbeat or now,
                    reason="error",
                    diagnostic="heartbeat_lost",
                    deferred=out.deferred,
                    now=now,
                )
            else:
                continue
            out.reaped.append(Reaped(call.id, call.status, call.room_name))
            logger.warning("reaped call %s -> %s (%s)", call.id, call.status, call.diagnostic)
    return out


async def reap_and_clean(
    db: Database, livekit: LiveKitGateway | None, queue: JobQueue | None, *, now: datetime | None = None
) -> ReapResult:
    result = await reap_stuck(db, now=now)
    await dispatch(queue, result.deferred)
    if livekit is not None:
        for reaped in result.reaped:
            if reaped.room:
                try:
                    await livekit.delete_room(reaped.room)
                except LiveKitError as exc:
                    logger.warning("could not delete room %s: %s", reaped.room, exc)
    return result


async def reap_stuck_calls(ctx: dict[str, Any]) -> int:
    result = await reap_and_clean(ctx["db"], ctx.get("livekit"), ctx.get("jobs"))
    return len(result.reaped)
