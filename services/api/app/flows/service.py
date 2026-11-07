"""Flows: create (agent plus flow), read, save with revision check, validate, compile, publish,
the call transition projection and the hooks other features call (T017, T018, T041, T068, T097,
T098, T103; data-model sections 1, 5, 6 and 9, research R2, R9, R15, R16).

Every function takes an ``AsyncSession`` scoped to the workspace (RLS).

Interfaces for other features:

* ``compile_draft(session, agent_id)``: the draft compiled for a test call (003, through the
  ``flow`` snapshot resolver registered in ``app.flows.hooks``).
* ``webhook_nodes_without_mock(session, agent_id)``: 005 mock coverage.
* ``tool_node_usages(session, tool_id)``: 005 tool usages with node ids.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.agents import service as agents
from app.agents.defaults import default_config
from app.agents.models import Agent
from app.calls.models import Call, CallEvent
from app.core.errors import ProblemError, not_found, validation_failed
from app.core.ids import new_id
from app.core.secrets import KeyWrapper, mask_secret, put_secret
from app.flows import compiler, validation
from app.flows.catalogs import check_overrides
from app.flows.models import Flow
from app.flows.starter import starter_graph
from app.tools import service as tools
from app.tools.models import Tool
from app.voices.catalog import DEFAULT_LANGUAGE
from app.voices.catalog import load_catalog as load_voice_catalog

tracer = trace.get_tracer("app.flows")

# Keys the Start node owns for flow agents, and keys the flow module manages itself.
START_OWNED = frozenset({"start_speaker", "begin_message"})
NOT_SETTINGS = frozenset({"type", "flow", "schema_version", "tools", "knowledge"})


def flow_revision_conflict(current: int, status: int = 412) -> ProblemError:
    return ProblemError(
        status,
        "flow_revision_conflict",
        "Flow changed",
        "This flow was saved somewhere else since you opened it. Reload to see the newer version.",
        extra={"current_revision": current},
    )


def agent_draft_changed(current: int) -> ProblemError:
    return ProblemError(
        412,
        "agent_draft_changed",
        "Settings changed",
        "The agent's settings were saved somewhere else since you opened the flow. Reload, then "
        "make your changes again. Nothing was saved.",
        extra={"current_revision": current},
    )


def agent_not_flow() -> ProblemError:
    return ProblemError(
        409, "agent_not_flow", "Not a flow agent", "This agent has no flow; open it in the agent editor."
    )


def flow_has_errors(issues: Sequence[Mapping[str, Any]]) -> ProblemError:
    errors = [dict(i) for i in issues if i.get("severity") == "error"]
    return ProblemError(
        422,
        "flow_has_errors",
        "Flow has errors",
        f"Fix the {len(errors)} error{'s' if len(errors) != 1 else ''} in the flow before publishing.",
        extra={"issues": errors},
    )


# Reads --------------------------------------------------------------------------------------


async def get_flow(session: AsyncSession, flow_id: str, *, lock: bool = False) -> Flow:
    stmt = select(Flow).where(Flow.id == flow_id)
    if lock:
        stmt = stmt.with_for_update()
    flow = (await session.execute(stmt)).scalar_one_or_none()
    if flow is None:
        raise not_found("flow")
    agent = await session.get(Agent, flow.agent_id)
    if agent is None or agent.deleted_at is not None:
        raise not_found("flow")
    return flow


async def flow_for_agent(session: AsyncSession, agent_id: str) -> Flow | None:
    return (await session.execute(select(Flow).where(Flow.agent_id == agent_id))).scalar_one_or_none()


async def get_flow_by_agent(session: AsyncSession, agent_id: str) -> Flow:
    agent = await agents.get_agent(session, agent_id)
    if agent.type != "flow":
        raise agent_not_flow()
    flow = await flow_for_agent(session, agent_id)
    if flow is None:
        raise not_found("flow")
    return flow


def flow_view(flow: Flow, agent: Agent | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": flow.id,
        "agent_id": flow.agent_id,
        "name": flow.name,
        "graph": masked_graph(flow.graph),
        "revision": flow.revision,
        "last_validation": flow.last_validation,
        "last_published_version_id": flow.last_published_version_id,
        "created_at": flow.created_at.isoformat(),
        "updated_at": flow.updated_at.isoformat(),
    }
    if agent is not None:
        body["agent_draft_revision"] = agent.draft_revision
    return body


def masked_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    """The graph with secret webhook header values hidden (T096). Secret headers are stored
    only as ``secret_ref`` plus ``masked_value``; a plain ``value`` on a secret header is never
    returned."""
    out = copy.deepcopy(dict(graph))
    for node in out.get("nodes") or []:
        if node.get("type") != "webhook":
            continue
        request = (node.get("config") or {}).get("request") or {}
        for header in request.get("headers") or []:
            if isinstance(header, dict) and header.get("secret") and header.get("value"):
                value = str(header.pop("value"))
                header["masked_value"] = header.get("masked_value") or mask_secret(value)
    return out


# Validation context ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowContext:
    agent: Agent
    validation: validation.ValidationContext
    tool_names: Mapping[str, str]


async def context_for(
    session: AsyncSession, agent: Agent, *, allow_http_webhook: bool = False
) -> FlowContext:
    config = agent.draft_config or {}
    rows = (await session.execute(select(Tool.id, Tool.name))).all()
    names = {str(r[0]): str(r[1]) for r in rows}
    declared = frozenset(
        str(v.get("name"))
        for v in config.get("dynamic_variables") or []
        if isinstance(v, Mapping) and v.get("name")
    )
    ctx = validation.ValidationContext(
        persona_prompt=str(config.get("prompt") or ""),
        defaulted_variables=declared,
        tools=names,
        flow_tool_names=tuple(names[t] for t in config.get("tool_ids") or [] if t in names),
        check_overrides=check_overrides,
        allow_http_webhook=allow_http_webhook,
    )
    return FlowContext(agent, ctx, names)


def result_of(issues: list[dict[str, Any]]) -> dict[str, Any]:
    errors, warnings = validation.counts(issues)
    return {
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "validated_at": datetime.now(UTC).isoformat(),
    }


async def validate_graph(
    session: AsyncSession, agent: Agent, graph: Mapping[str, Any], *, allow_http_webhook: bool = False
) -> dict[str, Any]:
    with tracer.start_as_current_span("flows.validate"):
        ctx = await context_for(session, agent, allow_http_webhook=allow_http_webhook)
        return result_of(validation.validate(graph, ctx.validation))


# Create -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Created:
    agent: Agent
    flow: Flow
    warnings: list[str]


async def create_flow_agent(
    session: AsyncSession, actor: agents.Actor, *, name: str, language: str
) -> Created:
    """The agent (002, type ``flow``, language defaults) and its flow with the starter graph, in
    the caller's transaction (FR-001, FR-003, research R15)."""
    with tracer.start_as_current_span("flows.create"):
        warnings: list[str] = []
        if load_voice_catalog().language(language) is None:
            warnings.append(
                f"{language} has no voice and speech defaults yet, so the {DEFAULT_LANGUAGE} "
                "defaults are used."
            )
            language = DEFAULT_LANGUAGE
        saved = await agents.create_agent(session, actor, name=name, agent_type="flow", language=language)
        graph = starter_graph()
        now = datetime.now(UTC)
        flow = Flow(
            id=new_id("flw"),
            workspace_id=actor.workspace_id,
            agent_id=saved.agent.id,
            name=name,
            graph=graph,
            revision=1,
            last_validation={},
            created_at=now,
            updated_at=now,
            updated_by=actor.user_id,
        )
        session.add(flow)
        await session.flush()
        flow.last_validation = await validate_graph(
            session, saved.agent, graph, allow_http_webhook=actor.allow_http_webhook
        )
        await session.flush()
        return Created(saved.agent, flow, warnings)


# Save ---------------------------------------------------------------------------------------


def _settings_errors(changes: Mapping[str, Any]) -> list[dict[str, str]]:
    allowed = set(default_config("flow")) - NOT_SETTINGS
    errors: list[dict[str, str]] = []
    for key in changes:
        pointer = f"/agent_settings/changes/{key}"
        if key in START_OWNED:
            errors.append(
                {
                    "pointer": pointer,
                    "code": "start_node_owned",
                    "message": "The Start node sets this for flow agents.",
                }
            )
        elif key not in allowed:
            errors.append(
                {"pointer": pointer, "code": "unknown_field", "message": "This is not an agent setting."}
            )
    return errors


async def _with_secrets(
    session: AsyncSession, wrapper: KeyWrapper | None, flow: Flow, graph: dict[str, Any]
) -> dict[str, Any]:
    """Keep secret webhook header values out of the stored graph: a new value is stored with
    005's secrets mechanism under a per-node name; a header sent back masked keeps its ref."""
    old_refs: dict[tuple[str, str], dict[str, Any]] = {}
    for node in flow.graph.get("nodes") or []:
        for h in ((node.get("config") or {}).get("request") or {}).get("headers") or []:
            if isinstance(h, dict) and h.get("secret") and h.get("secret_ref"):
                old_refs[(str(node.get("id")), str(h.get("name")))] = h
    for node in graph.get("nodes") or []:
        if node.get("type") != "webhook":
            continue
        for h in ((node.get("config") or {}).get("request") or {}).get("headers") or []:
            if not isinstance(h, dict) or not h.get("secret"):
                continue
            key = (str(node.get("id")), str(h.get("name")))
            value = h.get("value")
            if value and wrapper is not None:
                ref = f"flow_hdr:{flow.id}:{ULID()}"
                secret = await put_secret(session, wrapper, flow.workspace_id, ref, str(value))
                h.pop("value", None)
                h["secret_ref"] = ref
                h["masked_value"] = secret.masked
            elif key in old_refs:
                h["secret_ref"] = old_refs[key]["secret_ref"]
                h["masked_value"] = old_refs[key].get("masked_value")
    return graph


async def save_flow(
    session: AsyncSession,
    actor: agents.Actor,
    flow_id: str,
    *,
    expected_revision: int | None,
    name: str,
    graph: dict[str, Any],
    agent_settings: Mapping[str, Any] | None = None,
    wrapper: KeyWrapper | None = None,
) -> tuple[Flow, Agent]:
    """Store graph, name and changed flow-wide settings in one transaction (FR-046, FR-048)."""
    with tracer.start_as_current_span("flows.save"):
        flow = await get_flow(session, flow_id, lock=True)
        if expected_revision is None or expected_revision != flow.revision:
            raise flow_revision_conflict(flow.revision)
        if agent_settings is not None:
            errors = _settings_errors(agent_settings.get("changes") or {})
            if errors:
                raise validation_failed(errors)
        graph = await _with_secrets(session, wrapper, flow, copy.deepcopy(graph))
        flow.graph = graph
        flow.name = name
        flow.revision += 1
        flow.updated_at = datetime.now(UTC)
        flow.updated_by = actor.user_id
        await session.flush()
        if agent_settings is not None:
            try:
                saved = await agents.update_draft(
                    session,
                    actor,
                    flow.agent_id,
                    patch=agent_settings.get("changes") or {},
                    expected_revision=int(agent_settings["expected_draft_revision"]),
                    name=name,
                )
            except ProblemError as exc:
                if exc.code == "draft_changed":
                    raise agent_draft_changed(int(exc.extra.get("current_revision") or 0)) from exc
                raise
            agent = saved.agent
        else:
            agent = await agents.rename_agent(session, flow.agent_id, name)
        flow.last_validation = await validate_graph(
            session, agent, graph, allow_http_webhook=actor.allow_http_webhook
        )
        await session.flush()
        return flow, agent


# Compile and publish ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Compiled:
    issues: list[dict[str, Any]]
    compiled: dict[str, Any] | None


async def compile_graph(
    session: AsyncSession,
    flow: Flow,
    agent: Agent,
    graph: Mapping[str, Any],
    agent_config: Mapping[str, Any] | None = None,
    *,
    allow_http_webhook: bool = False,
) -> Compiled:
    config = agent_config if agent_config is not None else agent.draft_config
    ctx = await context_for(session, agent, allow_http_webhook=allow_http_webhook)
    issues = validation.validate(graph, ctx.validation)
    if any(i["severity"] == "error" for i in issues):
        return Compiled(issues, None)
    specs = await tools.resolve_for_snapshot(session, compiler.tool_ids_in(graph, config))
    by_id = {s.tool_id: s.model_dump(mode="json") for s in specs}
    return Compiled(issues, compiler.compile_flow(flow.id, graph, config, by_id))


async def compile_preview(
    session: AsyncSession, flow_id: str, *, allow_http_webhook: bool = False
) -> dict[str, Any]:
    flow = await get_flow(session, flow_id)
    agent = await agents.get_agent(session, flow.agent_id)
    result = await compile_graph(session, flow, agent, flow.graph, allow_http_webhook=allow_http_webhook)
    return {"ok": result.compiled is not None, "issues": result.issues, "compiled": result.compiled}


def flow_block(flow: Flow, compiled: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "flow_id": flow.id,
        "name": flow.name,
        "graph": copy.deepcopy(flow.graph),
        "graph_hash": compiler.graph_hash(flow.graph),
        "compiled": copy.deepcopy(dict(compiled)) if compiled is not None else None,
    }


async def compile_draft(
    session: AsyncSession, agent_id: str, agent_config: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """The ``config.flow`` block for the current draft (test calls, research R16), or ``None``
    when the agent has no flow. ``compiled`` is ``None`` while the draft has errors."""
    flow = await flow_for_agent(session, agent_id)
    if flow is None:
        return None
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return None
    result = await compile_graph(session, flow, agent, flow.graph, agent_config)
    block = flow_block(flow, result.compiled)
    if result.compiled is None:
        block["errors"] = sum(1 for i in result.issues if i["severity"] == "error")
    return block


@dataclass(frozen=True)
class Published:
    version_id: str
    version_number: int
    graph_hash: str
    warnings: int


async def publish(
    session: AsyncSession,
    actor: agents.Actor,
    flow_id: str,
    *,
    expected_revision: int,
    release_notes: str | None,
) -> Published:
    """Validate, compile and record a new published AgentVersion with ``config.flow`` (FR-027,
    FR-028). Live calls keep their version; new calls use this one."""
    with tracer.start_as_current_span("flows.publish") as span:
        flow = await get_flow(session, flow_id, lock=True)
        if expected_revision != flow.revision:
            raise flow_revision_conflict(flow.revision, status=409)
        agent = await agents.lock_agent(session, flow.agent_id)
        result = await compile_graph(
            session, flow, agent, flow.graph, allow_http_webhook=actor.allow_http_webhook
        )
        if result.compiled is None:
            raise flow_has_errors(result.issues)
        config = {**copy.deepcopy(agent.draft_config), "flow": flow_block(flow, result.compiled)}
        recorded = await agents.create_version(
            session,
            agent.id,
            config,
            note=release_notes or None,
            source="flow_publish",
            publish=True,
            user_id=actor.user_id,
            allow_http_webhook=actor.allow_http_webhook,
        )
        flow.last_published_version_id = recorded.version.id
        await session.flush()
        span.set_attribute("flow.graph_hash", result.compiled["graph_hash"])
        warnings = sum(1 for i in result.issues if i["severity"] == "warning")
        return Published(
            recorded.version.id, recorded.version.version_number, result.compiled["graph_hash"], warnings
        )


# Call transitions (read projection) ---------------------------------------------------------


def transition_view(event: CallEvent) -> dict[str, Any]:
    p = event.payload or {}
    t_ms = p.get("t_ms", event.offset_ms)
    return {
        "seq": event.seq,
        "from_node_id": p.get("from_node_id") or "",
        "from_label": p.get("from_label") or p.get("from_node_id") or "",
        "to_node_id": p.get("to_node_id") or "",
        "to_label": p.get("to_label") or p.get("to_node_id") or "",
        "edge_id": p.get("edge_id"),
        "edge_label": p.get("edge_label", p.get("label")),
        "trigger": p.get("trigger") or "llm_condition",
        "function_name": p.get("function_name"),
        "turn_index": int(p.get("turn_index") or event.turn_index or 0),
        "t_ms": int(t_ms or 0),
        "engine_ms": int(p.get("engine_ms") or 0),
        "model_ms": p.get("model_ms"),
    }


async def list_transitions(session: AsyncSession, call_id: str) -> list[dict[str, Any]]:
    """Ordered node moves of one call; empty for single-prompt agents (FR-034)."""
    if await session.get(Call, call_id) is None:
        raise not_found("call")
    rows = (
        await session.execute(
            select(CallEvent)
            .where(CallEvent.call_id == call_id, CallEvent.type == "flow_transition")
            .order_by(CallEvent.seq)
        )
    ).scalars()
    return [transition_view(e) for e in rows]


# Hooks for 005 --------------------------------------------------------------------------------


async def webhook_nodes_without_mock(session: AsyncSession, agent_id: str) -> list[dict[str, str]]:
    """Webhook nodes of the agent's draft flow with no canned response (005 mock coverage)."""
    flow = await flow_for_agent(session, agent_id)
    if flow is None:
        return []
    return [
        {"node_id": str(n.get("id")), "name": str(n.get("label") or n.get("id"))}
        for n in flow.graph.get("nodes") or []
        if n.get("type") == "webhook" and not str((n.get("config") or {}).get("mock_response") or "").strip()
    ]


async def tool_node_usages(session: AsyncSession, tool_id: str) -> list[dict[str, Any]]:
    """Draft flows whose nodes attach ``tool_id``: ``{agent_id, flow_id, node_ids}`` (005)."""
    rows = (
        await session.execute(
            select(Flow)
            .join(Agent, Agent.id == Flow.agent_id)
            .where(Agent.deleted_at.is_(None))
            .order_by(Flow.created_at)
        )
    ).scalars()
    out: list[dict[str, Any]] = []
    for flow in rows:
        ids = [
            str(n.get("id"))
            for n in flow.graph.get("nodes") or []
            if tool_id in ((n.get("config") or {}).get("tool_ids") or [])
        ]
        if ids:
            out.append({"agent_id": flow.agent_id, "flow_id": flow.id, "node_ids": ids})
    return out
