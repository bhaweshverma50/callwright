"""LiveKit webhook handlers (003 T082, T114; research R13, R16).

* ``room_finished``: second safety net after the worker's final status and the reaper. A call
  still connected is ended with ``error`` (billed to the last heartbeat); one that never
  connected is ``failed``.
* ``egress_started`` / ``egress_ended``: recording status and key. Ignored for calls whose
  recording setting is off: they stay ``not_recorded`` (no egress is started for them).
* ``participant_left``: logged; the worker reports hangups itself.

Handlers are idempotent; LiveKit may repeat events. Unknown events are acknowledged.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from app.call_events.service import version_config
from app.calls.effects import RUN_PIPELINE, Deferred
from app.calls.models import Call, billable_seconds
from app.core.db import Database
from app.webhooks_out import service as webhooks

logger = logging.getLogger(__name__)

EGRESS_COMPLETE = "EGRESS_COMPLETE"


async def _lookup(db: Database, function: str, value: str) -> tuple[str, str] | None:
    async with db.transaction() as session:
        row = (
            await session.execute(text(f"select call_id, workspace_id from {function}(:v)"), {"v": value})  # noqa: S608
        ).first()
    return (str(row.call_id), str(row.workspace_id)) if row is not None else None


async def room_finished(db: Database, room: str, now: datetime) -> tuple[str, Deferred]:
    deferred = Deferred()
    found = await _lookup(db, "calls_for_room", room)
    if found is None:
        return "unknown_room", deferred
    call_id, workspace_id = found
    async with db.transaction(workspace_id=workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id).with_for_update())).scalar_one()
        config = await version_config(session, call.agent_version_id)
        if call.status == "in_progress":
            assert call.connected_at is not None
            call.status = "ended"
            call.ended_at = max(call.connected_at, call.last_heartbeat_at or now)
            call.disconnect_reason = "error"
            call.diagnostic = "room_finished"
            call.billable_seconds = billable_seconds(call.connected_at, call.ended_at)
            await session.flush()
            await webhooks.enqueue_event(
                session, call, "call_ended", config=config, deferred=deferred, now=now
            )
            deferred.add(RUN_PIPELINE, workspace_id, call_id)
            return "ended", deferred
        if call.status in ("queued", "ringing"):
            call.status = "failed"
            call.disconnect_reason = "error"
            call.diagnostic = "room_finished_before_connect"
            call.billable_seconds = 0
            call.ended_at = now
            await session.flush()
            await webhooks.enqueue_event(
                session, call, "call_ended", config=config, deferred=deferred, now=now
            )
            return "failed", deferred
    return "already_closed", deferred


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
    found = await _lookup(db, "calls_for_egress", egress_id) if egress_id else None
    if found is None and room:
        found = await _lookup(db, "calls_for_room", room)
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


async def handle(db: Database, event: Mapping[str, Any], now: datetime | None = None) -> tuple[str, Deferred]:
    now = now or datetime.now(UTC)
    name = str(event.get("event") or "")
    if name == "room_finished":
        room = (event.get("room") or {}).get("name")
        if room:
            return await room_finished(db, str(room), now)
        return "no_room", Deferred()
    if name in ("egress_started", "egress_ended"):
        info = event.get("egressInfo") or event.get("egress_info") or {}
        return await egress_event(db, name, info if isinstance(info, Mapping) else {}), Deferred()
    if name == "participant_left":
        participant = event.get("participant") or {}
        logger.info(
            "participant %s left %s", participant.get("identity"), (event.get("room") or {}).get("name")
        )
        return "logged", Deferred()
    return "ignored", Deferred()
