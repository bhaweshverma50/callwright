"""Browser test calls (003 T030, research R17, R18).

Admission first (the room exists only for an admitted call), then room ``call-{call_id}``, a
dispatch of the voice worker with ``{"call_id"}`` as metadata, and a join token for this browser
only (one room, microphone and data publish, subscribe; 15 minutes). ``use_draft`` style access
for 005 and 008 is the ``version: "draft"`` selector (the default).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from callwright_contract.adapters import AdapterCatalog

from app.calls import service as calls
from app.core.config import Settings
from app.core.db import Database
from app.core.livekit import JOIN_TOKEN_TTL_S, LiveKitGateway
from app.core.queue import JobQueue, dispatch
from app.sessions.schemas import WebCallRequest, WebCallSession


class WebCaller(Protocol):
    """Who places the call: a signed-in member (``Principal``) or the homepage playground,
    which has a workspace but no user."""

    @property
    def workspace_id(self) -> str: ...

    @property
    def user_id(self) -> str | None: ...


@dataclass
class WebCallDeps:
    db: Database
    settings: Settings
    livekit: LiveKitGateway
    catalog: AdapterCatalog
    jobs: JobQueue | None


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
    room = await calls.start_room(
        deps.db, deps.livekit, deps.jobs, call, agent_name=deps.settings.worker_agent_name
    )
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
