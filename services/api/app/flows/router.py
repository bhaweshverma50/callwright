"""/v1/flows, /v1/agents/{agent_id}/flow and /v1/calls/{call_id}/flow-transitions
(contracts/flows.yaml; T019, T042, T068, T089)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse

from app.agents import service as agents
from app.agents.models import Agent
from app.agents.views import actor, parse_if_match
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import problem_responses
from app.core.ids import path_id
from app.core.secrets import key_wrapper
from app.flows import assistant, service
from app.flows.schemas import (
    NODE_TYPES,
    AssistantRequest,
    CreateFlowAgentRequest,
    PublishRequest,
    SaveFlowRequest,
    ValidateRequest,
    graph_json,
)
from app.flows.starter import DEFAULT_LABELS, node_defaults
from app.llms.runtime import runtime

router = APIRouter(tags=["flows"])

FlowId = Annotated[str, Depends(path_id("flw", "flow", "flow_id"))]
AgentId = Annotated[str, Depends(path_id("agt", "agent", "agent_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]


def _etag(revision: int) -> dict[str, str]:
    return {"ETag": f'"{revision}"'}


@router.post("/flows", status_code=201, responses=problem_responses(422))
async def create_flow_agent(
    body: CreateFlowAgentRequest, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    async with principal_tx(request, principal) as session:
        created = await service.create_flow_agent(
            session, actor(request, principal), name=body.name, language=body.language
        )
        out = {
            "agent_id": created.agent.id,
            "flow": service.flow_view(created.flow, created.agent),
            "warnings": created.warnings,
        }
    return JSONResponse(out, status_code=201, headers=_etag(created.flow.revision))


@router.get("/flows/node-defaults", responses=problem_responses(401))
async def get_node_defaults(principal: CurrentPrincipal) -> dict[str, Any]:
    """What a node of each type starts with in the builder: its label and full config."""
    return {
        "node_types": [
            {"type": t, "label": DEFAULT_LABELS[t], "config": node_defaults(t)} for t in NODE_TYPES
        ]
    }


@router.get("/flows/{flow_id}", responses=problem_responses(404))
async def get_flow(flow_id: FlowId, request: Request, principal: CurrentPrincipal) -> JSONResponse:
    async with principal_tx(request, principal) as session:
        flow = await service.get_flow(session, flow_id)
        agent = await session.get(Agent, flow.agent_id)
        body = service.flow_view(flow, agent)
    return JSONResponse(body, headers=_etag(flow.revision))


@router.put(
    "/flows/{flow_id}",
    responses={**problem_responses(404, 422), 412: {"description": "Flow or agent draft changed"}},
)
async def save_flow(
    flow_id: FlowId,
    body: SaveFlowRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: Annotated[str, Header(alias="If-Match")],
) -> JSONResponse:
    async with principal_tx(request, principal) as session:
        flow, agent = await service.save_flow(
            session,
            actor(request, principal),
            flow_id,
            expected_revision=parse_if_match(if_match),
            name=body.name,
            graph=graph_json(body.graph),
            agent_settings=body.agent_settings.model_dump() if body.agent_settings else None,
            wrapper=key_wrapper(request.app.state.settings),
        )
        out = service.flow_view(flow, agent)
    return JSONResponse(out, headers=_etag(flow.revision))


@router.get("/agents/{agent_id}/flow", responses=problem_responses(404, 409))
async def get_flow_by_agent(agent_id: AgentId, request: Request, principal: CurrentPrincipal) -> JSONResponse:
    async with principal_tx(request, principal) as session:
        flow = await service.get_flow_by_agent(session, agent_id)
        agent = await session.get(Agent, flow.agent_id)
        body = service.flow_view(flow, agent)
    return JSONResponse(body, headers=_etag(flow.revision))


@router.post("/flows/{flow_id}/validate", responses=problem_responses(404))
async def validate_flow(
    flow_id: FlowId,
    request: Request,
    principal: CurrentPrincipal,
    body: Annotated[ValidateRequest | None, Body()] = None,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        flow = await service.get_flow(session, flow_id)
        agent = await agents.get_agent(session, flow.agent_id)
        graph = graph_json(body.graph) if body is not None and body.graph is not None else flow.graph
        return await service.validate_graph(
            session, agent, graph, allow_http_webhook=request.app.state.settings.allow_http_webhooks
        )


@router.post("/flows/{flow_id}/compile", responses=problem_responses(404))
async def compile_flow(flow_id: FlowId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await service.compile_preview(
            session, flow_id, allow_http_webhook=request.app.state.settings.allow_http_webhooks
        )


@router.post(
    "/flows/{flow_id}/publish",
    status_code=201,
    responses={**problem_responses(404, 422), 409: {"description": "Flow changed"}},
)
async def publish_flow(
    flow_id: FlowId, body: PublishRequest, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    async with principal_tx(request, principal) as session:
        published = await service.publish(
            session,
            actor(request, principal),
            flow_id,
            expected_revision=body.expected_revision,
            release_notes=body.release_notes,
        )
    return JSONResponse(
        {
            "agent_version_id": published.version_id,
            "version_number": published.version_number,
            "graph_hash": published.graph_hash,
            "warnings": published.warnings,
        },
        status_code=201,
    )


@router.post(
    "/flows/{flow_id}/assistant",
    responses={
        **problem_responses(402, 404),
        409: {"description": "Stale base revision"},
        504: {"description": "Timed out"},
    },
)
async def ask_assistant(
    flow_id: FlowId, body: AssistantRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    state = request.app.state
    return await assistant.ask(
        state.db,
        state.settings,
        runtime().llm,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        flow_id=flow_id,
        request=body,
    )


@router.get("/calls/{call_id}/flow-transitions", responses=problem_responses(404))
async def list_flow_transitions(
    call_id: CallId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return {"items": await service.list_transitions(session, call_id)}
