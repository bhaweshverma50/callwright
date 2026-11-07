"""/v1 call labels (007 T046; contracts/annotations.yaml)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.annotations import service
from app.annotations.schemas import AnnotationPut
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import problem_responses
from app.core.ids import path_id

router = APIRouter(tags=["annotations"])
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]


@router.get("/calls/{call_id}/annotations", responses=problem_responses(404))
async def list_annotations(request: Request, principal: CurrentPrincipal, call_id: CallId) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await service.list_for_call(session, call_id, principal.user_id)


@router.put("/calls/{call_id}/annotations/me", responses=problem_responses(404, 422))
async def put_mine(
    request: Request, principal: CurrentPrincipal, call_id: CallId, body: AnnotationPut
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        row = await service.put_mine(
            session,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            email=principal.email,
            call_id=call_id,
            label=body.label,
            note=body.note,
        )
        return service.view(row)


@router.delete("/calls/{call_id}/annotations/me", status_code=204, responses=problem_responses(404))
async def delete_mine(request: Request, principal: CurrentPrincipal, call_id: CallId) -> Response:
    async with principal_tx(request, principal) as session:
        await service.delete_mine(session, call_id, principal.user_id)
    return Response(status_code=204)
