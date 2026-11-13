"""/v1/account/deletion: schedule and cancel account deletion."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.account import service
from app.account.schemas import DeletionRequest, DeletionScheduled
from app.core.auth import CurrentClaims, CurrentPrincipal, ScheduledPrincipal
from app.core.errors import problem_responses

router = APIRouter(prefix="/account", tags=["account"])


@router.post(
    "/deletion",
    status_code=202,
    response_model=DeletionScheduled,
    responses=problem_responses(401, 422, 429),
)
async def schedule_deletion(
    body: DeletionRequest, request: Request, claims: CurrentClaims, principal: CurrentPrincipal
) -> DeletionScheduled:
    scheduled = await service.schedule_deletion(
        request,
        principal,
        claims,
        confirm_workspace_name=body.confirm_workspace_name,
        password=body.password,
        confirm_email=body.confirm_email,
    )
    return DeletionScheduled(requested_at=scheduled.requested_at, scheduled_at=scheduled.scheduled_at)


@router.delete("/deletion", status_code=204, response_class=Response, responses=problem_responses(401))
async def cancel_deletion(request: Request, principal: ScheduledPrincipal) -> Response:
    await service.cancel_deletion(request, principal)
    return Response(status_code=204)
