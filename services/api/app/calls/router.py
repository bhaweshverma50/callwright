"""POST /v1/internal/calls/claim (contracts/calls.yaml, 003 T032). Service token only.

The read side (006) is ``read_router``.
"""

from __future__ import annotations

from typing import Any

from callwright_contract.protocol import ClaimRequest
from fastapi import APIRouter, Depends, Request

from app.calls import service
from app.core.auth import require_service
from app.core.errors import problem_responses
from app.core.queue import dispatch

router = APIRouter(tags=["calls-internal"], dependencies=[Depends(require_service)])


@router.post("/internal/calls/claim", responses=problem_responses(401, 404, 409))
async def claim_call(body: ClaimRequest, request: Request) -> dict[str, Any]:
    state = request.app.state
    outcome = await service.claim(
        state.db,
        body,
        catalog=state.adapter_catalog,
        media_bucket=state.settings.media_bucket,
    )
    await dispatch(getattr(state, "jobs", None), outcome.deferred)
    return outcome.body
