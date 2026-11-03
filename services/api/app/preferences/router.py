"""/v1/me/preferences (specs/013-guided-setup/contracts/preferences.yaml)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.preferences import service
from app.preferences.schemas import PreferencesOut, PreferencesUpdate

router = APIRouter(tags=["preferences"])


@router.get("/me/preferences", response_model=PreferencesOut, responses=problem_responses(401))
async def get_preferences(request: Request, principal: CurrentPrincipal) -> PreferencesOut:
    return await service.get_preferences(request.app.state.db, principal)


@router.patch("/me/preferences", response_model=PreferencesOut, responses=problem_responses(401, 422))
async def update_preferences(
    body: PreferencesUpdate, request: Request, principal: CurrentPrincipal
) -> PreferencesOut:
    return await service.update_onboarding(request.app.state.db, principal, body.onboarding)
