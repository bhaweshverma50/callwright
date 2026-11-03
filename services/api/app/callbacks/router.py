"""Scheduled callbacks (contracts/callbacks.yaml, 011): public list, get, create and cancel, and
the voice worker's booking endpoint (service token)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.call_events.service import workspace_for_call
from app.callbacks import service
from app.callbacks.schemas import CallbackBookRequest, CallbackCreate
from app.core.auth import CurrentPrincipal, require_service
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam

router = APIRouter(tags=["callbacks"])
internal_router = APIRouter(tags=["internal"], dependencies=[Depends(require_service)])

CallbackId = Annotated[str, Depends(path_id("cbk", "callback", "callback_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]
Status = Literal["scheduled", "placing", "placed", "cancelled", "failed"]


@router.get("/callbacks", responses=problem_responses(401))
async def list_callbacks(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: Status | None = None,
    source_call_id: Annotated[str | None, Query(pattern=r"^call_[0-9A-HJKMNP-TV-Z]{26}$")] = None,
) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return await service.list_callbacks(
            session, page=page, page_size=page_size, status=status, source_call_id=source_call_id
        )


@router.post("/callbacks", status_code=201, responses=problem_responses(401, 409, 422))
async def create_callback(
    body: CallbackCreate, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    out = await service.create(request.app.state.db, principal.workspace_id, principal.user_id, body)
    return JSONResponse(out, status_code=201)


@router.get("/callbacks/{callback_id}", responses=problem_responses(401, 404))
async def get_callback(
    callback_id: CallbackId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return await service.get_callback(session, callback_id)


@router.post("/callbacks/{callback_id}/cancel", responses=problem_responses(401, 404, 409))
async def cancel_callback(
    callback_id: CallbackId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        return await service.cancel(session, callback_id)


@internal_router.post(
    "/internal/calls/{call_id}/callbacks",
    status_code=201,
    responses={200: {"description": "Simulated call; nothing stored"}, **problem_responses(401, 404, 422)},
)
async def book_callback(call_id: CallId, body: CallbackBookRequest, request: Request) -> JSONResponse:
    db = request.app.state.db
    workspace_id = await workspace_for_call(db, call_id)
    status, out = await service.book_from_call(db, workspace_id, call_id, body)
    return JSONResponse(out, status_code=status)
