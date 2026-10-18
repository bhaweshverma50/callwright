"""Call jobs: post-call pipeline, recording start, stuck-call reaper, replay CLI (003 T057, T080,
T081, T083, T114; research R13, R14, R16).

arq entry points take ``ctx`` with ``db``, ``settings``, ``livekit``, ``jobs`` and
``adapter_catalog`` (built in ``app.core.jobs.startup``). The functions under them take explicit
arguments so tests run them without Redis.

Replay a call's pipeline (every step again; idempotent, so no second charge or notification)::

    uv run python -m app.calls.jobs replay <call_id>
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.call_events.service import version_config
from app.calls import pipeline
from app.calls.catalog import AdapterCatalog
from app.calls.effects import RUN_PIPELINE, Deferred, dispatch
from app.calls.models import Call, billable_seconds
from app.core.db import Database
from app.core.livekit import EgressTarget, LiveKitError, LiveKitGateway
from app.core.queue import JobQueue
from app.webhooks_out import service as webhooks

logger = logging.getLogger(__name__)

STUCK_QUEUED_S = 60
STUCK_HEARTBEAT_S = 60
RECORDING_UNAVAILABLE = "recording_unavailable"
"""Processing warning on a call whose recording could not start (no egress service)."""


def recording_key(workspace_id: str, call_id: str) -> str:
    return f"recordings/{workspace_id}/{call_id}.mp4"


# Pipeline ----------------------------------------------------------------------------------


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
        await queue.enqueue(RUN_PIPELINE, workspace_id, call_id, defer_by_s=result.retry_in_s)
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


# Recording -----------------------------------------------------------------------------------


async def start_recording_for(
    db: Database, livekit: LiveKitGateway, bucket: str, workspace_id: str, call_id: str
) -> str:
    """Start the dual-channel audio egress once per call. A no-op when recording is off (FR-044)."""
    async with db.transaction(workspace_id=workspace_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            return "missing"
        if not call.recording_enabled:
            return "not_recorded"
        if call.egress_id or call.recording_status != "none" or call.room_name is None:
            return "skipped"
        room = call.room_name
    key = recording_key(workspace_id, call_id)
    try:
        egress_id = await livekit.start_audio_recording(room, EgressTarget(bucket=bucket, key=key))
    except Exception as exc:
        # No egress service (or a broken one) never touches the call itself: it keeps running
        # unrecorded, the recording reads "unavailable" (failed) and the call carries the
        # ``recording_unavailable`` processing warning.
        logger.warning("recording unavailable for %s: %s", call_id, exc)
        async with db.transaction(workspace_id=workspace_id) as session:
            await session.execute(
                text(
                    "update calls set recording_status = 'failed', pipeline_warnings = case "
                    "when :warning = any(pipeline_warnings) then pipeline_warnings "
                    "else array_append(pipeline_warnings, :warning) end, "
                    # A short call can finish processing before the start gives up.
                    "pipeline_status = case when pipeline_status = 'done' then 'done_with_warnings' "
                    "else pipeline_status end "
                    "where id = :id and recording_status = 'none' and recording_enabled"
                ),
                {"id": call_id, "warning": RECORDING_UNAVAILABLE},
            )
        return "failed"
    async with db.transaction(workspace_id=workspace_id) as session:
        await session.execute(
            text(
                "update calls set egress_id = :egress, recording_key = :key, recording_status = 'recording' "
                "where id = :id and recording_enabled and egress_id is null and recording_status = 'none'"
            ),
            {"egress": egress_id, "key": key, "id": call_id},
        )
    return "started"


async def start_recording(ctx: dict[str, Any], workspace_id: str, call_id: str) -> str:
    return await start_recording_for(
        ctx["db"], ctx["livekit"], ctx["settings"].recordings_bucket, workspace_id, call_id
    )


# Reaper -------------------------------------------------------------------------------------


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
            config = await version_config(session, call.agent_version_id)
            if call.status == "queued":
                if call.created_at > now - timedelta(seconds=queued_s) or (heartbeat and heartbeat > stale):
                    continue
                diagnostic = (
                    "caller_never_joined"
                    if call.channel == "web" and call.claimed_at
                    else "worker_unavailable"
                )
                await _fail(session, call, diagnostic, now, config, out.deferred)
            elif call.status == "ringing":
                if (heartbeat or call.claimed_at or call.created_at) > stale:
                    continue
                await _fail(session, call, "heartbeat_lost", now, config, out.deferred)
            elif call.status == "in_progress":
                if (heartbeat or call.claimed_at or call.created_at) > stale:
                    continue
                assert call.connected_at is not None
                call.status = "ended"
                call.ended_at = max(call.connected_at, heartbeat or now)
                call.disconnect_reason = "error"
                call.diagnostic = "heartbeat_lost"
                call.billable_seconds = billable_seconds(call.connected_at, call.ended_at)
                await session.flush()
                await webhooks.enqueue_event(
                    session, call, "call_ended", config=config, deferred=out.deferred, now=now
                )
                out.deferred.add(RUN_PIPELINE, call.workspace_id, call.id)
            else:
                continue
            out.reaped.append(Reaped(call.id, call.status, call.room_name))
            logger.warning("reaped call %s -> %s (%s)", call.id, call.status, call.diagnostic)
    return out


async def _fail(
    session: Any, call: Call, diagnostic: str, now: datetime, config: Any, deferred: Deferred
) -> None:
    call.status = "failed"
    call.disconnect_reason = "error"
    call.diagnostic = diagnostic
    call.billable_seconds = 0
    call.ended_at = now
    await session.flush()
    await webhooks.enqueue_event(session, call, "call_ended", config=config, deferred=deferred, now=now)


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


# CLI -----------------------------------------------------------------------------------------


async def _replay(call_id: str) -> int:
    from app.calls.catalog import load_catalog
    from app.core.config import get_settings
    from app.core.queue import ArqJobQueue

    settings = get_settings()
    db = Database(settings.database_url, settings.database_admin_url, pool_size=2)
    queue = ArqJobQueue()
    try:
        async with db.transaction() as session:
            workspace_id = (
                await session.execute(text("select calls_workspace_for(:id)"), {"id": call_id})
            ).scalar()
        if workspace_id is None:
            print(f"no call {call_id}", file=sys.stderr)
            return 1
        result = await run_pipeline_for(
            db,
            queue,
            str(workspace_id),
            call_id,
            catalog=load_catalog(settings.adapter_catalog_path),
            recordings_bucket=settings.recordings_bucket,
            replay=True,
        )
        print(f"{call_id}: {result.status} {result.steps}")
        return 0 if result.status in ("finished", "not_ready") else 2
    finally:
        await queue.aclose()
        await db.dispose()


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "replay":
        print("usage: python -m app.calls.jobs replay <call_id>", file=sys.stderr)
        return 2
    return asyncio.run(_replay(argv[1]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
