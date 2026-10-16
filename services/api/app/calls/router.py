"""POST /v1/internal/calls/claim (contracts/calls.yaml, 003 T032). Service token only.

006 adds the read side (list, detail, recording URLs) to this module.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.calls import service
from app.calls.effects import dispatch
from app.calls.schemas import ClaimRequest
from app.core.auth import require_service
from app.core.errors import problem_responses

router = APIRouter(tags=["calls-internal"], dependencies=[Depends(require_service)])


@router.post("/internal/calls/claim", responses=problem_responses(401, 404, 409))
async def claim_call(body: ClaimRequest, request: Request) -> dict[str, Any]:
    state = request.app.state
    outcome = await service.claim(
        state.db,
        service.ClaimInput(
            job_id=body.job_id,
            room_name=body.room_name,
            worker_id=body.worker_id,
            dispatch_metadata=body.dispatch_metadata,
            sip=body.sip.model_dump(exclude_none=True) if body.sip else None,
        ),
        catalog=state.adapter_catalog,
        media_bucket=state.settings.media_bucket,
    )
    await dispatch(getattr(state, "jobs", None), outcome.deferred)
    return outcome.body
