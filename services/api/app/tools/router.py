"""/v1/tools, /v1/agents/{agent_id}/tools and the internal tool-secrets fetch
(specs/005-tools-knowledge/contracts/tools.yaml; T024, T044, T045, T086, T094)."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from callwright_contract.calls import ACTIVE_STATUSES
from callwright_contract.protocol import ToolSecrets
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.agent_versions.models import AgentVersion
from app.agents.views import actor
from app.calls.lookups import workspace_for_call
from app.calls.models import Call
from app.core import url_guard
from app.core.auth import CurrentPrincipal, bearer_token, principal_tx
from app.core.errors import ProblemError, not_found, problem_responses, too_many_requests, validation_failed
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.core.rate_limit import RateLimiter
from app.core.secrets import key_wrapper
from app.tools import http_exec, service
from app.tools.presets import PRESETS
from app.tools.schemas import SetAgentTools, TestRunRequest, ToolCreate, ToolType, ToolUpdate
from app.tools.validation import validate_config, validate_name

router = APIRouter(tags=["tools"])

ToolId = Annotated[str, Depends(path_id("tool", "tool", "tool_id"))]
AgentId = Annotated[str, Depends(path_id("agt", "agent", "agent_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]

TEST_RUNS_PER_MINUTE = 30


def _wrapper(request: Request) -> Any:
    return key_wrapper(request.app.state.settings)


async def _view(session: Any, tool: Any) -> dict[str, Any]:
    counts = await service.usage_counts(session, [tool.id])
    return service.tool_view(tool, counts.get(tool.id, 0))


@router.get("/tools", responses=problem_responses(401))
async def list_tools(
    request: Request,
    principal: CurrentPrincipal,
    type: Annotated[ToolType | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        rows, total = await service.list_tools(
            session, tool_type=type, search=search, page=page, page_size=page_size
        )
        counts = await service.usage_counts(session, [t.id for t in rows])
    return {
        "items": [service.tool_view(t, counts.get(t.id, 0)) for t in rows],
        **page_meta(total, page, page_size),
    }


@router.post("/tools", status_code=201, responses=problem_responses(422))
async def create_tool(body: ToolCreate, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        tool = await service.create_tool(session, actor(request, principal), _wrapper(request), body)
        return service.tool_view(tool, 0)


@router.get("/tools/presets")
async def list_tool_presets(principal: CurrentPrincipal) -> dict[str, Any]:
    return {"items": list(PRESETS)}


@router.post("/tools/test-run", responses=problem_responses(422, 429))
async def test_run_tool(
    body: TestRunRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    limit = await RateLimiter(request.app.state.redis).hit(
        "tool_test_run", principal.workspace_id, limit=TEST_RUNS_PER_MINUTE, window_s=60
    )
    if not limit.allowed:
        raise too_many_requests(
            limit.retry_after_s, "Test runs are limited to 30 a minute. Try again shortly."
        )
    allow_http = request.app.state.settings.allow_http_webhooks
    secrets: dict[str, str] = {}
    async with principal_tx(request, principal) as session:
        if body.tool_id is not None:
            tool = await service.get_tool(session, body.tool_id)
            tool_type, spec = tool.type, dict(tool.config)
            secrets = await service.secrets_for_config(
                session, _wrapper(request), principal.workspace_id, {"tools": [{"config": spec}]}
            )
        else:
            assert body.tool is not None
            tool_type, spec = body.tool.type, dict(body.tool.config)
    if tool_type != "http":
        raise validation_failed(
            [{"pointer": "/tool/type", "code": "not_allowed", "message": "Only HTTP tools can be test-run."}]
        )
    if body.tool is not None:
        issues = validate_name(body.tool.name, "/tool/name") + [
            {**i, "pointer": "/tool" + i["pointer"]}
            for i in validate_config("http", spec, allow_http=allow_http)
        ]
        if issues:
            raise validation_failed(issues)
        spec = service.normalized_config("http", spec)
    client = getattr(request.app.state, "tool_http", None) or request.app.state.webhook_http
    return await http_exec.run(
        spec,
        body.arguments,
        body.dynamic_variables,
        client=client,
        secrets=secrets,
        allow_http=allow_http,
        resolver=url_guard.resolver,
    )


@router.get("/tools/{tool_id}", responses=problem_responses(404))
async def get_tool(tool_id: ToolId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await _view(session, await service.get_tool(session, tool_id))


@router.patch("/tools/{tool_id}", responses=problem_responses(404, 422))
async def update_tool(
    tool_id: ToolId, body: ToolUpdate, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        tool = await service.update_tool(session, actor(request, principal), _wrapper(request), tool_id, body)
        return await _view(session, tool)


@router.delete("/tools/{tool_id}", responses=problem_responses(404, 409))
async def delete_tool(
    tool_id: ToolId,
    request: Request,
    principal: CurrentPrincipal,
    force: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        detached = await service.delete_tool(session, actor(request, principal), tool_id, force=force)
    return {"deleted": True, "detached_agent_ids": detached}


@router.post("/tools/{tool_id}/duplicate", status_code=201, responses=problem_responses(404))
async def duplicate_tool(tool_id: ToolId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        tool = await service.duplicate_tool(session, actor(request, principal), _wrapper(request), tool_id)
        return service.tool_view(tool, 0)


@router.get("/tools/{tool_id}/usages", responses=problem_responses(404))
async def get_tool_usages(tool_id: ToolId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        await service.get_tool(session, tool_id)
        found = await service.usages(session, tool_id)
        nodes = await service.flow_node_usages(session, tool_id)
        names = {u.agent_id for u in found}
        extra = [a for a in nodes if a not in names]
        named = {a: n for a, n in (await service.agent_names(session, extra)).items()} if extra else {}
    items: list[dict[str, Any]] = [
        {
            "agent_id": u.agent_id,
            "agent_name": u.agent_name,
            "in_draft": u.in_draft,
            "published_version_ids": u.published_version_ids,
            **({"flow_node_ids": nodes[u.agent_id]} if u.agent_id in nodes else {}),
        }
        for u in found
    ]
    items += [
        {
            "agent_id": a,
            "agent_name": named.get(a, a),
            "in_draft": True,
            "published_version_ids": [],
            "flow_node_ids": nodes[a],
        }
        for a in extra
    ]
    return {"items": items}


async def _tool_set(session: Any, agent_id: str, tools: list[Any]) -> dict[str, Any]:
    counts = await service.usage_counts(session, [t.id for t in tools])
    return {"agent_id": agent_id, "tools": [service.tool_view(t, counts.get(t.id, 0)) for t in tools]}


@router.get("/agents/{agent_id}/tools", responses=problem_responses(404))
async def get_agent_tools(agent_id: AgentId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await _tool_set(session, agent_id, await service.agent_tools(session, agent_id))


@router.put("/agents/{agent_id}/tools", responses=problem_responses(404, 422))
async def set_agent_tools(
    agent_id: AgentId, body: SetAgentTools, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        tools = await service.set_agent_tools(session, actor(request, principal), agent_id, body.tool_ids)
        return await _tool_set(session, agent_id, tools)


@router.get("/agents/{agent_id}/tools/mock-coverage", responses=problem_responses(404))
async def get_agent_tool_mock_coverage(
    agent_id: AgentId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await service.mock_coverage(session, agent_id)


def _require_service_or_hide(request: Request) -> None:
    """Callers without the worker's service token get 404, so the endpoint is not discoverable."""
    try:
        token = bearer_token(request)
    except ProblemError as exc:
        raise not_found("call") from exc
    expected = request.app.state.settings.service_token.get_secret_value()
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise not_found("call")


@router.get(
    "/internal/calls/{call_id}/tool-secrets",
    tags=["internal"],
    responses=problem_responses(403, 404, 409),
)
async def get_call_tool_secrets(call_id: CallId, request: Request) -> JSONResponse:
    _require_service_or_hide(request)
    state = request.app.state
    workspace_id = await workspace_for_call(state.db, call_id)
    async with state.db.transaction(workspace_id=workspace_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            raise not_found("call")
        if call.status not in ACTIVE_STATUSES:
            raise ProblemError(
                409, "call_closed", "Call is closed", "Secrets are only served for live calls."
            )
        if call.agent_version_id is None:
            raise ProblemError(403, "forbidden", "Not allowed", "The call has no agent version.")
        version = await session.get(AgentVersion, call.agent_version_id)
        config = version.config if version is not None else {}
        secrets = await service.secrets_for_config(session, key_wrapper(state.settings), workspace_id, config)
    return JSONResponse(ToolSecrets(secrets=secrets).model_dump(), headers={"Cache-Control": "no-store"})
