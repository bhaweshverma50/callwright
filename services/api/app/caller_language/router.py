"""Caller language (contracts/caller_language.yaml, 012): saved caller languages, the call view
and the voice worker's switch report (service token)."""

from __future__ import annotations

from typing import Annotated, Any

from callwright_contract.values import E164_PATTERN
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.caller_language import service
from app.calls.lookups import workspace_for_call
from app.core.auth import CurrentPrincipal, require_service
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam

router = APIRouter(tags=["caller-language"])
internal_router = APIRouter(tags=["internal"], dependencies=[Depends(require_service)])

PreferenceId = Annotated[str, Depends(path_id("cpf", "caller_preference", "preference_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]


class LanguageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(min_length=2, max_length=16)
    offset_ms: int | None = Field(default=None, ge=0)


@router.get("/caller-preferences", responses=problem_responses(401))
async def list_caller_preferences(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    phone_number: Annotated[str | None, Query(pattern=E164_PATTERN)] = None,
) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return await service.list_preferences(
            session, page=page, page_size=page_size, phone_number=phone_number
        )


@router.delete("/caller-preferences/{preference_id}", status_code=204, responses=problem_responses(401, 404))
async def delete_caller_preference(
    preference_id: PreferenceId, request: Request, principal: CurrentPrincipal
) -> Response:
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        await service.delete_preference(session, preference_id)
    return Response(status_code=204)


@router.get("/calls/{call_id}/language", responses=problem_responses(401, 404))
async def get_call_language(call_id: CallId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return await service.call_language(session, call_id)


@internal_router.post("/internal/calls/{call_id}/language", responses=problem_responses(401, 404, 422))
async def report_call_language(call_id: CallId, body: LanguageReport, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    workspace_id = await workspace_for_call(db, call_id)
    return await service.report_switch(db, workspace_id, call_id, body.language, body.offset_ms)
