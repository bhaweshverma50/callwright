"""/v1/me and /v1/workspaces/current (contracts/workspaces.yaml)."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request

from app.auth.service import auth_service
from app.core.auth import CurrentPrincipal, ScheduledPrincipal
from app.core.errors import problem_responses
from app.workspaces import service
from app.workspaces.schemas import MeOut, WorkspaceOut, WorkspaceUpdate

router = APIRouter(tags=["workspaces"])


@router.get("/me", response_model=MeOut, responses=problem_responses(401))
async def get_me(request: Request, principal: ScheduledPrincipal) -> MeOut:
    """Also answers for an account scheduled for deletion (``user.deletion_scheduled_at``), so the
    web can show its locked screen."""
    me = await service.get_me(request.app.state.db, principal)
    has_password = await auth_service(request).has_password(me.user.idp_subject)
    return MeOut.from_view(replace(me, has_password=has_password))


@router.patch("/workspaces/current", response_model=WorkspaceOut, responses=problem_responses(401, 422))
async def update_current_workspace(
    body: WorkspaceUpdate, request: Request, principal: CurrentPrincipal
) -> WorkspaceOut:
    workspace = await service.update_workspace(
        request.app.state.db, principal, name=body.name, recording_default=body.recording_default
    )
    return WorkspaceOut.model_validate(workspace, from_attributes=True)
