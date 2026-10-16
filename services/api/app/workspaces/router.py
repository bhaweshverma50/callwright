"""/v1/me and /v1/workspaces/current (contracts/workspaces.yaml)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.workspaces import service
from app.workspaces.schemas import MeOut, WorkspaceOut, WorkspaceUpdate

router = APIRouter(tags=["workspaces"])


@router.get("/me", response_model=MeOut, responses=problem_responses(401))
async def get_me(request: Request, principal: CurrentPrincipal) -> MeOut:
    return MeOut.from_view(await service.get_me(request.app.state.db, principal))


@router.patch("/workspaces/current", response_model=WorkspaceOut, responses=problem_responses(401, 422))
async def update_current_workspace(
    body: WorkspaceUpdate, request: Request, principal: CurrentPrincipal
) -> WorkspaceOut:
    workspace = await service.update_workspace(
        request.app.state.db, principal, name=body.name, recording_default=body.recording_default
    )
    return WorkspaceOut.model_validate(workspace, from_attributes=True)
