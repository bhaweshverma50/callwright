"""LiveKit webhook handlers (003 T082, T114; research R13, R16).

* ``room_finished``: second safety net after the worker's final status and the reaper. A call
  still connected is ended with ``error`` (billed to the last heartbeat); one that never
  connected is ``failed``.
* ``egress_started`` / ``egress_ended``: the recording's status (``recordings.egress``).
* ``participant_left``: logged; the worker reports hangups itself.

Handlers are idempotent; LiveKit may repeat events. Unknown events are acknowledged.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.calls import lifecycle
from app.calls.lookups import call_for_room
from app.calls.models import Call
from app.core.db import Database
from app.core.queue import Deferred
from app.recordings.egress import egress_event

logger = logging.getLogger(__name__)


async def room_finished(db: Database, room: str, now: datetime) -> tuple[str, Deferred]:
    deferred = Deferred()
    found = await call_for_room(db, room)
    if found is None:
        return "unknown_room", deferred
    call_id, workspace_id = found
    async with db.transaction(workspace_id=workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id).with_for_update())).scalar_one()
        if call.status == "in_progress":
            await lifecycle.end_connected(
                session,
                call,
                at=call.last_heartbeat_at or now,
                reason="error",
                diagnostic="room_finished",
                deferred=deferred,
                now=now,
            )
            return "ended", deferred
        if call.status in ("queued", "ringing"):
            await lifecycle.fail_unconnected(
                session, call, at=now, diagnostic="room_finished_before_connect", deferred=deferred, now=now
            )
            return "failed", deferred
    return "already_closed", deferred


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
