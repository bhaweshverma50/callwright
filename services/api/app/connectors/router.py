"""/v1/connections (specs/022-knowledge-connectors/contracts/connectors.yaml; T026, T045).

Google sign-in starts here and is completed by the web app's callback page, which posts the code
and state back with the user's bearer token (research R4). Only the workspace owner adds,
reconnects and removes connections (FR-007). Tokens never appear in any response (FR-004).
"""

from __future__ import annotations

import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.connectors import oauth, service
from app.connectors.schemas import CompleteBody, StartBody
from app.core.auth import CurrentPrincipal, Principal, principal_tx
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.secrets import key_wrapper
from app.knowledge.sources import drive_client

router = APIRouter(tags=["connections"])

ConnectionId = Annotated[str, Depends(path_id("conn", "connection", "connection_id"))]


def deps(request: Request) -> service.ConnectorDeps:
    settings = request.app.state.settings
    return service.ConnectorDeps(
        settings=settings, redis=request.app.state.redis, wrapper=key_wrapper(settings), drive=drive_client()
    )


@router.get("/connections", responses=problem_responses(401))
async def list_connections(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        items = await service.list_views(session)
    return {"items": items, "google_configured": request.app.state.settings.google_configured}


@router.post("/connections/google/start", responses=problem_responses(401, 403, 404, 503))
async def start_google_connection(
    request: Request, principal: CurrentPrincipal, body: StartBody | None = None
) -> dict[str, Any]:
    d = deps(request)
    service.ensure_configured(d.settings)
    connection_id = body.connection_id if body else None
    async with principal_tx(request, principal) as session:
        await service.require_owner(session, principal.workspace_id, principal.user_id)
        if connection_id:
            await service.get_connection(session, connection_id)
    url = await oauth.start(
        d.redis,
        d.settings,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        connection_id=connection_id,
    )
    return {"authorization_url": url, "expires_in_s": oauth.STATE_TTL_S}


@router.post(
    "/connections/google/complete",
    responses={201: {"description": "New connection"}, **problem_responses(400, 401, 403, 503)},
)
async def complete_google_connection(
    body: CompleteBody, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    d = deps(request)
    service.ensure_configured(d.settings)
    async with principal_tx(request, principal) as session:
        await service.require_owner(session, principal.workspace_id, principal.user_id)
        conn, created = await service.complete(
            session,
            d,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            state=body.state,
            code=body.code,
            error=body.error,
        )
        users = (await service.users_of(session, [conn.id])).get(conn.id, [])
        payload = service.view(conn, len(users))
    return JSONResponse(payload, status_code=201 if created else 200)


async def _connection(request: Request, principal: Principal, connection_id: str) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await service.detail_view(session, await service.get_connection(session, connection_id))


@router.get("/connections/{connection_id}", responses=problem_responses(401, 404))
async def get_connection(
    connection_id: ConnectionId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await _connection(request, principal, connection_id)


@router.delete(
    "/connections/{connection_id}", status_code=204, responses=problem_responses(401, 403, 404, 409)
)
async def delete_connection(
    connection_id: ConnectionId, request: Request, principal: CurrentPrincipal
) -> Response:
    d = deps(request)
    async with principal_tx(request, principal) as session:
        await service.require_owner(session, principal.workspace_id, principal.user_id)
        conn = await service.get_connection(session, connection_id)
        refresh = await service.remove(session, d, conn, principal.user_id)
    if refresh:
        with contextlib.suppress(Exception):
            await d.drive.revoke(refresh)
    return Response(status_code=204)


@router.post("/connections/{connection_id}/test", responses=problem_responses(401, 404, 503))
async def test_connection(
    connection_id: ConnectionId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    d = deps(request)
    service.ensure_configured(d.settings)
    async with principal_tx(request, principal) as session:
        conn = await service.test(session, d, await service.get_connection(session, connection_id))
        users = (await service.users_of(session, [conn.id])).get(conn.id, [])
        return service.view(conn, len(users))
