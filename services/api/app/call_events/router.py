"""POST /v1/internal/calls/{call_id}/events (contracts/call_events.yaml, 003 T033). Service token.

The workspace comes from the call row, never from the body (R19).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.call_events import service
from app.call_events.schemas import EventBatch
from app.calls.effects import dispatch
from app.core.auth import require_service
from app.core.errors import problem_responses

router = APIRouter(tags=["call-events-internal"], dependencies=[Depends(require_service)])


@router.post("/internal/calls/{call_id}/events", responses=problem_responses(401, 404, 409, 422))
async def post_call_events(call_id: str, body: EventBatch, request: Request) -> dict[str, Any]:
    state = request.app.state
    outcome = await service.ingest(
        state.db,
        call_id,
        body,
        catalog=state.adapter_catalog,
        grace_usd=state.settings.credit_grace_usd,
    )
    await dispatch(getattr(state, "jobs", None), outcome.deferred)
    return outcome.result.model_dump(exclude_none=True)
