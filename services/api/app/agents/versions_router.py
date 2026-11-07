"""/v1/agents/{agent_id}/versions and /published-version (contracts/agent_versions.yaml; T060)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agents import service, versions, views
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import not_found, problem_responses, validation_failed
from app.core.ids import is_valid_id, path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta

router = APIRouter(tags=["agent_versions"])

AgentId = Annotated[str, Depends(path_id("agt", "agent", "agent_id"))]
VersionId = Annotated[str, Depends(path_id("agv", "version", "version_id"))]


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)
    publish: bool = False


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str = Field(pattern=r"^agv_[0-9A-HJKMNP-TV-Z]{26}$")


def _allow_http(request: Request) -> bool:
    return bool(request.app.state.settings.allow_http_webhooks)


@router.get("/agents/{agent_id}/versions", responses=problem_responses(401, 404))
async def list_agent_versions(
    agent_id: AgentId,
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    include_test: bool = False,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        agent = await service.get_agent(session, agent_id, include_deleted=True)
        rows, total = await versions.list_versions(
            session, agent.id, page=page, page_size=page_size, include_test=include_test
        )
        items = await views.version_summaries(session, agent, rows)
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/agents/{agent_id}/versions/{version_id}", responses=problem_responses(401, 404))
async def get_agent_version(
    agent_id: AgentId, version_id: VersionId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        agent = await service.get_agent(session, agent_id, include_deleted=True)
        version = await versions.get_for_agent(session, agent.id, version_id)
        return await views.version_detail(session, agent, version)


@router.get("/agents/{agent_id}/versions/{version_id}/diff", responses=problem_responses(404))
async def diff_agent_version(
    agent_id: AgentId,
    version_id: VersionId,
    request: Request,
    principal: CurrentPrincipal,
    against: Annotated[
        str | None, Query(description="Another version id of the same agent, or draft")
    ] = None,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        agent = await service.get_agent(session, agent_id, include_deleted=True)
        await versions.get_for_agent(session, agent.id, version_id)
        if against is None:
            raise validation_failed(
                [{"pointer": "/query/against", "code": "required", "message": "Choose what to compare with."}]
            )
        if against != "draft" and not is_valid_id(against, "agv"):
            raise not_found("version")
        return await versions.diff(session, agent, version_id, against)


@router.post(
    "/agents/{agent_id}/versions/{version_id}/restore",
    responses={**problem_responses(404, 422), 412: {"description": "Draft changed"}},
)
async def restore_agent_version(
    agent_id: AgentId,
    version_id: VersionId,
    request: Request,
    principal: CurrentPrincipal,
    if_match: Annotated[str, Header(alias="If-Match")],
    body: Annotated[RestoreRequest | None, Body()] = None,
) -> JSONResponse:
    body = body or RestoreRequest()
    async with principal_tx(request, principal) as session:
        outcome = await service.restore(
            session,
            agent_id,
            version_id,
            expected_revision=views.parse_if_match(if_match),
            note=body.note,
            publish_now=body.publish,
            user_id=principal.user_id,
            allow_http_webhook=_allow_http(request),
        )
        result = await views.save_result(
            session,
            outcome.agent,
            outcome.version,
            created=True,
            warnings=outcome.warnings,
            publish_blockers=outcome.publish_blockers,
        )
    return JSONResponse(result, headers={"ETag": views.etag(outcome.agent)})


@router.put("/agents/{agent_id}/published-version", responses=problem_responses(404, 422))
async def publish_agent_version(
    agent_id: AgentId, body: PublishRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        agent = await service.publish(
            session, agent_id, body.version_id, allow_http_webhook=_allow_http(request)
        )
        return await views.agent_summary_for(session, agent)


@router.delete("/agents/{agent_id}/published-version", status_code=204, responses=problem_responses(404))
async def unpublish_agent(agent_id: AgentId, request: Request, principal: CurrentPrincipal) -> Response:
    async with principal_tx(request, principal) as session:
        await service.unpublish(session, agent_id)
    return Response(status_code=204)
