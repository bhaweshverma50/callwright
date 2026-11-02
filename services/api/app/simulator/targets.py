"""Simulation and test targets (008 T008; research R3, FR-012).

``resolve_target`` turns ``published | draft | version | variant`` into a full snapshot through
002's agent versions: the published version, a version matching the saved draft
(``snapshot_for_test``, which never publishes), a given version, or a variant whose complete
configuration comes with the request. Variants are checked with the same rules as a save
(002's validator, which runs 004's flow and 005's tool hooks), and a flow variant must carry a
compiled flow with its entry node. The snapshot's hash is the canonical-JSON SHA-256 that
versions use (``agent_versions.canonical.content_hash``), so hashes compare across features.
Variants also keep a diff against their base version for display.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions import service as versions
from app.agent_versions.canonical import content_hash
from app.agent_versions.diff import diff_configs
from app.agents.checks import validate_config
from app.agents.models import Agent
from app.agents.schemas import upcast
from app.core.errors import ProblemError, field_error, not_found, validation_failed

TARGET_TYPES = ("published", "draft", "version", "variant")


@dataclass(frozen=True)
class ResolvedTarget:
    target_type: str
    agent_version_id: str | None
    config: dict[str, Any]
    config_hash: str
    variant_label: str | None = None
    variant_diff: list[dict[str, Any]] | None = None


def canonical_hash(snapshot: Any) -> str:
    """SHA-256 over canonical JSON (sorted keys, no whitespace); 009 compares targets with it."""
    return content_hash(snapshot)


async def require_agent(session: AsyncSession, agent_id: str, *, pointer: str | None = None) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        if pointer:
            raise validation_failed(
                [field_error(pointer, "invalid_format", "Choose an agent of this workspace")]
            )
        raise not_found("agent")
    return agent


def agent_type_of(agent: Agent | str) -> str:
    kind = agent if isinstance(agent, str) else agent.type
    return "flow" if kind == "flow" else "single_prompt"


def has_agent_node(config: Mapping[str, Any]) -> bool:
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    nodes = compiled.get("nodes") if isinstance(compiled, Mapping) else None
    if not isinstance(nodes, Mapping):
        return False
    return any(isinstance(n, Mapping) and n.get("type") in ("agent", "task") for n in nodes.values())


def runnable_problem(agent_type: str, config: Mapping[str, Any]) -> ProblemError | None:
    """409 when the configuration has nothing to answer with (US1 scenario 6)."""
    if agent_type == "flow":
        if not has_agent_node(config):
            return ProblemError(
                409,
                "agent_not_runnable",
                "Agent cannot answer yet",
                "This flow has no agent node. Add one in the flow builder, then run the tests.",
            )
        return None
    if not str(config.get("prompt") or "").strip():
        return ProblemError(
            409,
            "agent_not_runnable",
            "Agent cannot answer yet",
            "This agent has no prompt. Write one in the agent editor, then run the tests.",
        )
    return None


def agent_model(config: Mapping[str, Any]) -> str:
    llm = config.get("llm")
    llm = llm if isinstance(llm, Mapping) else {}
    return f"{llm.get('provider') or 'azure_openai'}/{llm.get('model') or 'gpt-5.1'}"


def _target_error(pointer: str, message: str) -> ProblemError:
    return validation_failed([field_error(pointer, "invalid_format", message)])


async def _snapshot(session: AsyncSession, agent: Agent, version_id: str) -> versions.AgentSnapshot:
    version = await versions.get(session, version_id)
    if version is None or version.agent_id != agent.id:
        raise _target_error("/target/agent_version_id", "Choose a version of this agent")
    return await versions.get_snapshot(session, version_id)


def _flow_problems(config: Mapping[str, Any]) -> list[dict[str, str]]:
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    if not isinstance(compiled, Mapping):
        return [field_error("/target/config/flow", "invalid_format", "The flow has errors. Fix them first.")]
    nodes = compiled.get("nodes")
    entry = compiled.get("entry_node_id")
    if not isinstance(nodes, Mapping) or not entry or entry not in nodes:
        return [field_error("/target/config/flow", "invalid_format", "The flow has no Start node.")]
    return []


async def _compile_variant_flow(
    session: AsyncSession, agent: Agent, config: dict[str, Any], base: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Compile a flow variant whose graph was edited (004's compiler), so the runner runs the
    edited instructions. A variant without a graph keeps the base version's compiled flow."""
    from app.flows import compiler
    from app.flows import service as flows

    block = config.get("flow")
    graph = block.get("graph") if isinstance(block, Mapping) else None
    base_flow = base.get("flow") if isinstance(base.get("flow"), Mapping) else None
    if not isinstance(graph, Mapping):
        if base_flow is not None and not (isinstance(block, Mapping) and block.get("compiled")):
            config["flow"] = dict(base_flow)
        return []
    if (
        isinstance(block, Mapping)
        and block.get("compiled")
        and base_flow is not None
        and compiler.graph_hash(graph) == base_flow.get("graph_hash")
    ):
        return []
    flow = await flows.flow_for_agent(session, agent.id)
    if flow is None:
        return [field_error("/target/config/flow", "invalid_format", "This agent has no flow.")]
    result = await flows.compile_graph(session, flow, agent, graph, config)
    if result.compiled is None:
        return [
            field_error(
                "/target/config/flow" + str(i.get("pointer") or ""), "invalid_format", str(i.get("message"))
            )
            for i in result.issues
            if i.get("severity") == "error"
        ] or [field_error("/target/config/flow", "invalid_format", "The flow has errors. Fix them first.")]
    config["flow"] = {
        "flow_id": flow.id,
        "name": flow.name,
        "graph": dict(graph),
        "graph_hash": compiler.graph_hash(graph),
        "compiled": result.compiled,
    }
    return []


def variant_diff(base: Mapping[str, Any], variant: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for change in diff_configs(dict(base), dict(variant)):
        entry: dict[str, Any] = {"op": change["op"], "path": change["path"]}
        if "new" in change:
            entry["value"] = change["new"]
        if "old" in change:
            entry["old"] = change["old"]
        out.append(entry)
    return out


async def resolve_target(
    session: AsyncSession,
    agent: Agent,
    target: Mapping[str, Any] | None,
    *,
    default: str = "published",
    allow_variant: bool = True,
) -> ResolvedTarget:
    target = dict(target or {})
    kind = str(target.get("type") or default)
    if kind not in TARGET_TYPES or (kind == "variant" and not allow_variant):
        raise _target_error("/target/type", "Choose the published version, the saved draft or a version")
    if kind == "published":
        if agent.pinned_version_id is None:
            raise ProblemError(
                409,
                "agent_not_published",
                "Agent not published",
                "This agent has no published version. Publish it or choose the saved draft.",
            )
        snapshot = await versions.get_snapshot(session, agent.pinned_version_id)
        return ResolvedTarget(kind, snapshot.version_id, snapshot.config, canonical_hash(snapshot.config))
    if kind == "draft":
        version = await versions.snapshot_for_test(session, agent.id)
        snapshot = await versions.get_snapshot(session, version.id)
        return ResolvedTarget(kind, snapshot.version_id, snapshot.config, canonical_hash(snapshot.config))
    if kind == "version":
        version_id = target.get("agent_version_id")
        if not isinstance(version_id, str) or not version_id:
            raise _target_error("/target/agent_version_id", "Choose a version of this agent")
        snapshot = await _snapshot(session, agent, version_id)
        return ResolvedTarget(kind, snapshot.version_id, snapshot.config, canonical_hash(snapshot.config))
    # Variant: a complete configuration based on a version (the published one by default).
    raw = target.get("config")
    if not isinstance(raw, Mapping) or not raw:
        raise _target_error("/target/config", "A variant needs the full agent configuration")
    base_id = target.get("agent_version_id") or agent.pinned_version_id or agent.draft_version_id
    base = await _snapshot(session, agent, str(base_id))
    config = upcast(dict(raw))
    # Blocks only a version snapshot carries (tools, knowledge) come from the base when the
    # variant leaves them out (a variant edited from the saved draft has none).
    for block in ("tools", "knowledge"):
        if block not in config and block in base.config:
            config[block] = base.config[block]
    if agent_type_of(agent) == "flow":
        compile_errors = await _compile_variant_flow(session, agent, config, base.config)
        if compile_errors:
            raise validation_failed(compile_errors)
    result = await validate_config(
        agent.type,
        versions.draft_part(config),
        agent.id,
        session=session,
        workspace_id=agent.workspace_id,
    )
    problems = [{**e, "pointer": "/target/config" + str(e.get("pointer") or "")} for e in result.errors]
    if agent_type_of(agent) == "flow":
        problems += _flow_problems(config)
    if problems:
        raise validation_failed(problems)
    label = target.get("label")
    return ResolvedTarget(
        kind,
        base.version_id,
        config,
        canonical_hash(config),
        variant_label=str(label)[:60] if isinstance(label, str) and label.strip() else "Variant",
        variant_diff=variant_diff(base.config, config),
    )
