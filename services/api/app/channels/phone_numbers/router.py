"""/v1/phone-numbers (contracts/phone_numbers.yaml, 010 T018, T040)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.channels.phone_numbers import service
from app.channels.phone_numbers.schemas import PhoneNumberImport, PhoneNumberUpdate
from app.channels.shared import ChannelDeps
from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam

router = APIRouter(tags=["phone-numbers"])

NumberId = Annotated[str, Depends(path_id("num", "phone number", "number_id"))]


def channel_deps(request: Request) -> ChannelDeps:
    state = request.app.state
    return ChannelDeps(db=state.db, settings=state.settings, sip=state.sip)


Deps = Annotated[ChannelDeps, Depends(channel_deps)]


@router.get("/phone-numbers", responses=problem_responses(401))
async def list_phone_numbers(
    principal: CurrentPrincipal,
    deps: Deps,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    status: Annotated[Literal["provisioning", "active", "error", "draining"] | None, Query()] = None,
) -> dict[str, Any]:
    return await service.list_numbers(
        deps, principal.workspace_id, page=page, page_size=page_size, status=status
    )


@router.post("/phone-numbers", status_code=201, responses=problem_responses(401, 409, 422))
async def import_phone_number(
    body: PhoneNumberImport, principal: CurrentPrincipal, deps: Deps
) -> JSONResponse:
    return JSONResponse(await service.import_number(deps, principal, body), status_code=201)


@router.get("/phone-numbers/sip-settings", responses=problem_responses(401))
async def get_sip_settings(principal: CurrentPrincipal, deps: Deps) -> dict[str, Any]:
    return service.sip_settings(deps)


@router.get("/phone-numbers/{number_id}", responses=problem_responses(401, 404))
async def get_phone_number(number_id: NumberId, principal: CurrentPrincipal, deps: Deps) -> dict[str, Any]:
    return await service.get_number(deps, principal.workspace_id, number_id)


@router.patch("/phone-numbers/{number_id}", responses=problem_responses(401, 404, 409, 422, 502))
async def update_phone_number(
    number_id: NumberId, body: PhoneNumberUpdate, principal: CurrentPrincipal, deps: Deps
) -> dict[str, Any]:
    return await service.update_number(deps, principal, number_id, body)


@router.delete(
    "/phone-numbers/{number_id}",
    status_code=204,
    responses={202: {"description": "Draining"}, **problem_responses(401, 404, 409, 502)},
)
async def delete_phone_number(
    number_id: NumberId, principal: CurrentPrincipal, deps: Deps, when_idle: bool = False
) -> Response:
    status, body = await service.delete_number(deps, principal.workspace_id, number_id, when_idle=when_idle)
    if body is None:
        return Response(status_code=204)
    return JSONResponse(body, status_code=status)


@router.post("/phone-numbers/{number_id}/retry-provisioning", responses=problem_responses(401, 404, 409))
async def retry_phone_number_provisioning(
    number_id: NumberId, principal: CurrentPrincipal, deps: Deps
) -> dict[str, Any]:
    return await service.retry_provisioning(deps, principal.workspace_id, number_id)
