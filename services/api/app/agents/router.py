"""/v1/agents (contracts/agents.yaml; T033, T050, T098)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from app.agents import service, views
from app.agents.idempotency import AgentIdempotency
from app.agents.schemas import (
    AgentType,
    CreateAgentRequest,
    DuplicateRequest,
    RenameRequest,
    SaveDraftRequest,
    ValidateRequest,
)
from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta

router = APIRouter(tags=["agents"])

AgentId = Annotated[str, Depends(path_id("agt", "agent", "agent_id"))]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)]


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


def actor(request: Request, principal: Principal) -> service.Actor:
    return service.Actor(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        allow_http_webhook=request.app.state.settings.env == "dev",
    )


Created = tuple[str, list[dict[str, str]]]


async def _idempotent_create(
    request: Request, principal: Principal, key: str | None, create: Callable[[], Awaitable[Created]]
) -> JSONResponse:
    """Run ``create`` (which returns the new agent id and its creation warnings, such as
    replaced template components) once per Idempotency-Key, then answer with the agent's
    detail."""
    guard = AgentIdempotency(request.app.state.redis, principal.workspace_id, key) if key else None
    agent_id = await guard.claim_or_existing() if guard else None
    created_warnings: list[dict[str, str]] = []
    if agent_id is None:
        try:
            agent_id, created_warnings = await create()
        except BaseException:
            if guard:
                await guard.release()
            raise
        if guard:
            await guard.complete(agent_id)
    async with _tx(request, principal) as session:
        agent = await service.get_agent(session, agent_id)
        result = await service.validate_config(
            agent.type, agent.draft_config, agent.id, session=session, workspace_id=agent.workspace_id
        )
        result.warnings[:0] = [w for w in created_warnings if w not in result.warnings]
        body = await views.agent_detail(session, agent, result)
    return JSONResponse(body, status_code=201, headers={"ETag": views.etag(agent)})


@router.get("/agents", responses=problem_responses(401))
async def list_agents(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
    type: Annotated[AgentType | None, Query()] = None,
    status: Annotated[Literal["live", "draft", "attention"] | None, Query()] = None,
    sort: Annotated[Literal["updated", "name", "created"], Query()] = "updated",
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total, counts = await service.list_agents(
            session,
            page=page,
            page_size=page_size,
            search=search,
            agent_type=type,
            status=status,
            sort=sort,
        )
    items = [
        views.agent_summary(
            row.agent,
            {
                "id": row.agent.pinned_version_id,
                "version_number": row.published_number,
                "created_at": row.published_created_at.isoformat(),
            }
            if row.published_number is not None and row.published_created_at is not None
            else None,
            row.has_publish_blockers,
        )
        for row in rows
    ]
    return {"items": items, "counts": counts, **page_meta(total, page, page_size)}


@router.post("/agents", status_code=201, responses=problem_responses(401, 404, 422))
async def create_agent(
    body: CreateAgentRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    async def create() -> Created:
        async with _tx(request, principal) as session:
            saved = await service.create_agent(
                session,
                actor(request, principal),
                name=body.name,
                agent_type=body.type,
                language=body.language,
                config=body.config,
                template_id=body.template_id,
            )
            return saved.agent.id, saved.validation.warnings

    return await _idempotent_create(request, principal, idempotency_key, create)


@router.get("/agents/defaults", responses=problem_responses(401))
async def get_agent_defaults(
    principal: CurrentPrincipal,
    type: Annotated[AgentType, Query()] = "single_prompt",
    language: Annotated[str, Query(max_length=16)] = "en-US",
) -> dict[str, Any]:
    return service.agent_defaults(type, language)


@router.post("/agents/validate", responses=problem_responses(401))
async def validate_agent_config(
    body: ValidateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        result = await service.validate_config(
            body.type,
            body.config,
            body.agent_id,
            session=session,
            workspace_id=principal.workspace_id,
            allow_http_webhook=request.app.state.settings.env == "dev",
        )
    return result.json()


@router.get("/agents/{agent_id}", responses=problem_responses(401, 404))
async def get_agent(agent_id: AgentId, request: Request, principal: CurrentPrincipal) -> JSONResponse:
    async with _tx(request, principal) as session:
        agent = await service.get_agent(session, agent_id)
        result = await service.validate_config(
            agent.type, agent.draft_config, agent.id, session=session, workspace_id=agent.workspace_id
        )
        body = await views.agent_detail(session, agent, result)
    return JSONResponse(body, headers={"ETag": views.etag(agent)})


@router.patch("/agents/{agent_id}", responses=problem_responses(404, 422))
async def rename_agent(
    agent_id: AgentId, body: RenameRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        agent = await service.rename_agent(session, agent_id, body.name)
        return await views.agent_summary_for(session, agent)


@router.delete("/agents/{agent_id}", status_code=204, responses=problem_responses(404, 409))
async def delete_agent(agent_id: AgentId, request: Request, principal: CurrentPrincipal) -> Response:
    async with _tx(request, principal) as session:
        await service.delete_agent(session, actor(request, principal), agent_id)
    return Response(status_code=204)


@router.put(
    "/agents/{agent_id}/draft",
    responses={**problem_responses(404, 422), 412: {"description": "Draft changed"}},
)
async def save_agent_draft(
    agent_id: AgentId,
    body: SaveDraftRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: Annotated[str, Header(alias="If-Match")],
) -> JSONResponse:
    async with _tx(request, principal) as session:
        saved = await service.update_draft(
            session,
            actor(request, principal),
            agent_id,
            config=body.config,
            expected_revision=views.parse_if_match(if_match),
            name=body.name,
            note=body.note,
        )
        result = await views.save_result(
            session,
            saved.agent,
            saved.version,
            created=saved.created,
            warnings=saved.validation.warnings,
            publish_blockers=saved.validation.publish_blockers,
        )
    return JSONResponse(result, headers={"ETag": views.etag(saved.agent)})


@router.post("/agents/{agent_id}/duplicate", status_code=201, responses=problem_responses(404))
async def duplicate_agent(
    agent_id: AgentId,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey = None,
    body: Annotated[DuplicateRequest | None, Body()] = None,
) -> JSONResponse:
    async def create() -> Created:
        async with _tx(request, principal) as session:
            saved = await service.duplicate_agent(
                session,
                actor(request, principal),
                agent_id,
                body.name if body else None,
                body.version_id if body else None,
            )
            return saved.agent.id, saved.validation.warnings

    return await _idempotent_create(request, principal, idempotency_key, create)
