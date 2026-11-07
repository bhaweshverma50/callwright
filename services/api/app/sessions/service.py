"""Browser test calls (003 T030, research R17, R18).

Admission first (the room exists only for an admitted call), then room ``call-{call_id}``, a
dispatch of the voice worker with ``{"call_id"}`` as metadata, and a join token for this browser
only (one room, microphone and data publish, subscribe; 15 minutes). ``use_draft`` style access
for 005 and 008 is the ``version: "draft"`` selector (the default).
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from callwright_contract.adapters import AdapterCatalog
from callwright_contract.protocol import DISPATCH_CALL_ID

from app.calls import service as calls
from app.calls.effects import Deferred, dispatch
from app.calls.models import Call
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError
from app.core.livekit import JOIN_TOKEN_TTL_S, LiveKitError, LiveKitGateway
from app.core.queue import JobQueue
from app.sessions.schemas import WebCallRequest, WebCallSession

logger = logging.getLogger(__name__)


class WebCaller(Protocol):
    """Who places the call: a signed-in member (``Principal``) or the homepage playground,
    which has a workspace but no user."""

    @property
    def workspace_id(self) -> str: ...

    @property
    def user_id(self) -> str | None: ...


def room_name(call_id: str) -> str:
    return f"call-{call_id}"


@dataclass
class WebCallDeps:
    db: Database
    settings: Settings
    livekit: LiveKitGateway
    catalog: AdapterCatalog
    jobs: JobQueue | None


def media_unavailable(call_id: str) -> ProblemError:
    return ProblemError(
        503,
        "media_unavailable",
        "Call could not start",
        "The realtime media server is unavailable. The call was not charged; try again.",
        extra={"call_id": call_id, "disconnect_reason": "error", "diagnostic": "room_unavailable"},
    )


async def start_web_call(
    deps: WebCallDeps, principal: WebCaller, body: WebCallRequest, *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    admission = await calls.admit(
        deps.db,
        calls.AdmissionRequest(
            workspace_id=principal.workspace_id,
            agent_id=body.agent_id,
            channel="web",
            direction="inbound",
            version=body.version,
            origin="test",
            variables=body.dynamic_variables,
            metadata=body.metadata,
            initiated_by_user_id=principal.user_id,
        ),
        catalog=deps.catalog,
        now=now,
    )
    await dispatch(deps.jobs, admission.deferred)
    call = admission.call
    if not admission.admitted:
        assert admission.refusal is not None
        raise admission.refusal.problem(call.id)
    room = room_name(call.id)
    try:
        metadata = {DISPATCH_CALL_ID: call.id}
        await deps.livekit.create_room(room, metadata=json.dumps(metadata, separators=(",", ":")))
        await deps.livekit.dispatch_agent(room, deps.settings.worker_agent_name, metadata)
    except LiveKitError:
        logger.exception("room setup failed for %s", call.id)
        deferred = Deferred()
        await calls.mark_failed(deps.db, call.workspace_id, call.id, "room_unavailable", deferred=deferred)
        await dispatch(deps.jobs, deferred)
        try:
            await deps.livekit.delete_room(room)
        except LiveKitError:
            logger.warning("could not delete room %s after a failed setup", room)
        raise media_unavailable(call.id) from None
    async with deps.db.transaction(workspace_id=call.workspace_id) as session:
        row = await session.get(Call, call.id)
        assert row is not None
        row.room_name = room
    identity = f"web-{principal.user_id or 'demo'}-{secrets.token_hex(3)}"
    token = deps.livekit.join_token(room=room, identity=identity, name="You", ttl_s=JOIN_TOKEN_TTL_S)
    assert admission.snapshot is not None
    session_body = WebCallSession(
        call_id=call.id,
        agent_version_id=admission.snapshot.version_id,
        room_name=room,
        server_url=deps.settings.livekit_client_url,
        participant_token=token,
        expires_at=(now + timedelta(seconds=JOIN_TOKEN_TTL_S)).isoformat(),
        status="queued",
        missing_variables=list(call.missing_variables or []),
        ignored_overrides=list(call.ignored_overrides or []),
    )
    return session_body.model_dump()
