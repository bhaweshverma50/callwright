"""/v1/whatsapp (contracts/whatsapp.yaml, 010 T053, T058). The webhook routes are public."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam
from app.whatsapp import service
from app.whatsapp.schemas import (
    CallerRouteCreate,
    CallerRouteUpdate,
    WhatsAppChannelCreate,
    WhatsAppChannelUpdate,
)

router = APIRouter(tags=["whatsapp"])
public_router = APIRouter(tags=["whatsapp-public"])

ChannelId = Annotated[str, Depends(path_id("wa", "WhatsApp channel", "channel_id"))]
RouteId = Annotated[str, Depends(path_id("wcr", "caller route", "route_id"))]
ListSize = Annotated[int, Query(ge=1, le=100)]


def whatsapp_deps(request: Request) -> service.WhatsAppDeps:
    state = request.app.state
    return service.WhatsAppDeps(
        db=state.db, settings=state.settings, sip=state.sip, graph=state.whatsapp_graph
    )


Deps = Annotated[service.WhatsAppDeps, Depends(whatsapp_deps)]


@router.get("/whatsapp/settings", responses=problem_responses(401))
async def get_whatsapp_settings(principal: CurrentPrincipal, deps: Deps) -> dict[str, Any]:
    return service.settings_view(deps)


@router.get("/whatsapp/channels", responses=problem_responses(401))
async def list_whatsapp_channels(
    principal: CurrentPrincipal, deps: Deps, page: PageParam = 1, page_size: PageSizeParam = 20
) -> dict[str, Any]:
    return await service.list_channels(deps, principal.workspace_id, page=page, page_size=page_size)


@router.post("/whatsapp/channels", status_code=201, responses=problem_responses(401, 409, 422, 502))
async def create_whatsapp_channel(
    body: WhatsAppChannelCreate, principal: CurrentPrincipal, deps: Deps
) -> JSONResponse:
    return JSONResponse(await service.create_channel(deps, principal, body), status_code=201)


@router.get("/whatsapp/channels/{channel_id}", responses=problem_responses(401, 404))
async def get_whatsapp_channel(
    channel_id: ChannelId, principal: CurrentPrincipal, deps: Deps
) -> dict[str, Any]:
    return await service.get_channel(deps, principal.workspace_id, channel_id)


@router.patch("/whatsapp/channels/{channel_id}", responses=problem_responses(401, 404, 409, 422, 502))
async def update_whatsapp_channel(
    channel_id: ChannelId, body: WhatsAppChannelUpdate, principal: CurrentPrincipal, deps: Deps
) -> dict[str, Any]:
    return await service.update_channel(deps, principal, channel_id, body)


@router.delete(
    "/whatsapp/channels/{channel_id}",
    status_code=204,
    responses={202: {"description": "Draining"}, **problem_responses(401, 404, 409, 502)},
)
async def delete_whatsapp_channel(
    channel_id: ChannelId, principal: CurrentPrincipal, deps: Deps, when_idle: bool = False
) -> Response:
    status, body = await service.delete_channel(deps, principal.workspace_id, channel_id, when_idle=when_idle)
    if body is None:
        return Response(status_code=204)
    return JSONResponse(body, status_code=status)


@router.post("/whatsapp/channels/{channel_id}/retry-setup", responses=problem_responses(401, 404, 409))
async def retry_whatsapp_setup(
    channel_id: ChannelId, principal: CurrentPrincipal, deps: Deps
) -> dict[str, Any]:
    return await service.retry_setup(deps, principal.workspace_id, channel_id)


@router.get("/whatsapp/channels/{channel_id}/caller-routes", responses=problem_responses(401, 404))
async def list_caller_routes(
    channel_id: ChannelId,
    principal: CurrentPrincipal,
    deps: Deps,
    page: PageParam = 1,
    page_size: ListSize = 50,
    caller: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    return await service.list_routes(
        deps, principal.workspace_id, channel_id, page=page, page_size=page_size, caller=caller
    )


@router.post(
    "/whatsapp/channels/{channel_id}/caller-routes",
    status_code=201,
    responses=problem_responses(401, 404, 409, 422),
)
async def create_caller_route(
    channel_id: ChannelId, body: CallerRouteCreate, principal: CurrentPrincipal, deps: Deps
) -> JSONResponse:
    return JSONResponse(
        await service.create_route(deps, principal.workspace_id, channel_id, body), status_code=201
    )


@router.patch(
    "/whatsapp/channels/{channel_id}/caller-routes/{route_id}", responses=problem_responses(401, 404, 422)
)
async def update_caller_route(
    channel_id: ChannelId, route_id: RouteId, body: CallerRouteUpdate, principal: CurrentPrincipal, deps: Deps
) -> dict[str, Any]:
    return await service.update_route(deps, principal.workspace_id, channel_id, route_id, body.agent_id)


@router.delete(
    "/whatsapp/channels/{channel_id}/caller-routes/{route_id}",
    status_code=204,
    responses=problem_responses(401, 404),
)
async def delete_caller_route(
    channel_id: ChannelId, route_id: RouteId, principal: CurrentPrincipal, deps: Deps
) -> Response:
    await service.delete_route(deps, principal.workspace_id, channel_id, route_id)
    return Response(status_code=204)


# Public callback (Meta) ---------------------------------------------------------------------


@public_router.get(
    "/whatsapp/webhook",
    response_class=PlainTextResponse,
    responses={403: {"description": "Unknown verify token"}},
)
async def verify_whatsapp_webhook(
    request: Request,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    verify_token: Annotated[str | None, Query(alias="hub.verify_token", max_length=256)] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge", max_length=256)] = None,
) -> PlainTextResponse:
    deps = whatsapp_deps(request)
    echoed = await service.verify_challenge(deps, mode, verify_token, challenge)
    if echoed is None:
        return PlainTextResponse("Forbidden", status_code=403)
    return PlainTextResponse(echoed)


@public_router.post("/whatsapp/webhook", responses={401: {"description": "Signature does not match"}})
async def receive_whatsapp_webhook(
    request: Request,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> Response:
    body = await request.body()
    status = await service.receive_notification(whatsapp_deps(request), body, signature)
    return Response(status_code=status)
