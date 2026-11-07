"""``GET /v1/calls/{call_id}/recording`` (006 T032, contracts/recordings.yaml)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace

from app.calls.models import Call
from app.calls.ports import registry
from app.core.auth import CurrentPrincipal
from app.core.errors import not_found, problem_responses
from app.core.ids import path_id
from app.recordings.service import recording_link

router = APIRouter(tags=["recordings"])
tracer = trace.get_tracer("app.recordings")
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]


@router.get("/calls/{call_id}/recording", responses=problem_responses(401, 404, 409, 410))
async def get_recording(
    call_id: CallId,
    request: Request,
    principal: CurrentPrincipal,
    disposition: Annotated[Literal["inline", "attachment"], Query()] = "inline",
) -> JSONResponse:
    state = request.app.state
    with tracer.start_as_current_span("recordings.link", attributes={"call_id": call_id}):
        async with state.db.transaction(
            workspace_id=principal.workspace_id, user_id=principal.user_id
        ) as session:
            call = await session.get(Call, call_id)
        if call is None:
            raise not_found("call")
        if registry.signer is None:
            raise not_found("recording")
        body = recording_link(
            call,
            registry.signer,
            state.settings.recordings_bucket,
            ttl_s=state.settings.recording_url_ttl_s,
            disposition=disposition,
            now=datetime.now(UTC),
        )
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
