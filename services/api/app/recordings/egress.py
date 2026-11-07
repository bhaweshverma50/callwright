"""Call recordings: the egress start, its LiveKit status events and the sweep for lost ones
(003 T081, T082, T114; research R13).

* ``start_recording`` (job, deferred by the claim): starts the dual-channel audio egress once per
  call; a no-op when recording is off (FR-044). No egress service (or a broken one) never touches
  the call: it goes on unrecorded, the recording reads ``failed`` and the call carries the
  ``recording_unavailable`` processing warning.
* ``egress_event``: ``egress_started`` / ``egress_ended`` set the recording status and key;
  ignored for calls whose recording is off.
* ``settle_stuck_recordings`` (cron): recordings whose ``egress_ended`` webhook never arrived (API
  cold, VM restarted mid-delivery) are read back from LiveKit and applied as if the webhook had
  come. One LiveKit no longer knows (its server restarted) is failed after ``RECORDING_LOST_S``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.calls.lookups import call_for_egress, call_for_room
from app.calls.models import Call
from app.core.db import Database
from app.core.livekit import EgressTarget, LiveKitError, LiveKitGateway

logger = logging.getLogger(__name__)

RECORDING_UNAVAILABLE = "recording_unavailable"
"""Processing warning on a call whose recording could not start (no egress service)."""
RECORDING_SETTLE_AFTER_S = 120
RECORDING_LOST_S = 1800
EGRESS_COMPLETE = "EGRESS_COMPLETE"
EGRESS_DONE = (EGRESS_COMPLETE, "EGRESS_FAILED", "EGRESS_ABORTED", "EGRESS_LIMIT_REACHED")


def recording_key(workspace_id: str, call_id: str) -> str:
    return f"recordings/{workspace_id}/{call_id}.mp4"


async def start_recording_for(
    db: Database, livekit: LiveKitGateway, bucket: str, workspace_id: str, call_id: str
) -> str:
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


def _file_key(info: Mapping[str, Any]) -> str | None:
    results = info.get("fileResults") or info.get("file_results") or []
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, Mapping):
            name = first.get("filename")
            return str(name) if name else None
    return None


async def egress_event(db: Database, event: str, info: Mapping[str, Any]) -> str:
    egress_id = str(info.get("egressId") or info.get("egress_id") or "")
    room = str(info.get("roomName") or info.get("room_name") or "")
    found = await call_for_egress(db, egress_id) if egress_id else None
    if found is None and room:
        found = await call_for_room(db, room)
    if found is None:
        return "unknown_egress"
    call_id, workspace_id = found
    async with db.transaction(workspace_id=workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id).with_for_update())).scalar_one()
        if not call.recording_enabled:
            return "ignored_not_recorded"
        if call.egress_id and egress_id and call.egress_id != egress_id:
            return "ignored_other_egress"
        if event == "egress_started":
            if call.recording_status == "none":
                call.recording_status = "recording"
                call.egress_id = call.egress_id or egress_id or None
            return "recording"
        status = str(info.get("status") or "")
        if status == EGRESS_COMPLETE:
            call.recording_status = "available"
            call.recording_key = _file_key(info) or call.recording_key
        else:
            call.recording_status = "failed"
            logger.warning("recording failed for %s: %s %s", call_id, status, info.get("error"))
        call.egress_id = call.egress_id or egress_id or None
        return call.recording_status


async def settle_recordings(db: Database, livekit: LiveKitGateway, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with db.transaction() as session:
        rows = (
            await session.execute(
                text("select call_id, egress_id, ended_at from calls_recording_pending(:s)"),
                {"s": RECORDING_SETTLE_AFTER_S},
            )
        ).all()
    settled = 0
    for row in rows:
        try:
            info = await livekit.egress_info(row.egress_id)
        except LiveKitError as exc:
            logger.info("recording sweep: LiveKit unreachable (%s)", exc)
            break
        if info is None:
            if row.ended_at > now - timedelta(seconds=RECORDING_LOST_S):
                continue
            info = {"egressId": row.egress_id, "status": "EGRESS_LOST"}
        elif info.get("status") not in EGRESS_DONE:
            continue
        await egress_event(db, "egress_ended", info)
        settled += 1
    return settled


async def settle_stuck_recordings(ctx: dict[str, Any]) -> int:
    livekit = ctx.get("livekit")
    return await settle_recordings(ctx["db"], livekit) if livekit is not None else 0
