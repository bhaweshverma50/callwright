"""AI flow assistant (T088, T113; FR-036 to FR-039, FR-049, research R17, data-model section 7).

Stateless: the browser sends the chat each time. Order: base revision check (409), balance
(402), one model call with a 60 s limit (504, never charged), then the answer's operations are
remapped (``tmp_*`` and other unknown new ids become ``n_``/``e_`` ids), applied to a copy of
the graph, placed and validated, and the request is charged once as ``flow_assistant``.
Nothing is saved: the client applies ``proposed_graph`` only when the operator approves.

Node configs from the assistant never carry ``overrides`` (FR-038): they are removed before
the operations are applied or returned.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from opentelemetry import trace

from app.agents import service as agents
from app.agents.schemas import NAME_MAX
from app.billing import service as billing
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError
from app.flows import service, validation
from app.flows.schemas import NODE_TYPES, AssistantRequest, FlowGraph
from app.flows.starter import DEFAULT_LABELS, config_with_defaults, short_id
from app.llms.client import (
    ChatMessage,
    LlmClient,
    ModelError,
    ModelRef,
    ModelTimeout,
    billable_cost,
    token_cost,
)
from app.pricing.engine import fmt6

tracer = trace.get_tracer("app.flows")
SYSTEM_PROMPT = Path(__file__).with_name("assistant_prompt.md").read_text(encoding="utf-8")
MAX_OUTPUT_TOKENS = 6000
NODE_W, NODE_H = 248, 136  # card size with outcome rows (data model assumes at least 240 x 96)
RANKSEP = 120
STEP_Y = 40
EDGE_CHANGE_KEYS = ("label", "condition", "target", "category", "rule", "trigger")


class UnknownReference(ValueError):
    """An operation names a node or edge that is not in the graph."""


def assistant_timeout() -> ProblemError:
    return ProblemError(
        504,
        "assistant_timeout",
        "Assistant did not answer",
        "The assistant did not answer within 60 seconds. Nothing was charged and the flow is "
        "unchanged; try again.",
    )


def model_for(settings: Settings) -> str:
    if settings.flow_assistant_model:
        return settings.flow_assistant_model
    if settings.openai_api_key:
        return "openai/gpt-5-mini"
    return settings.prompt_ai_model


# Operations -------------------------------------------------------------------------------------


def _strip_overrides(config: Any) -> dict[str, Any]:
    cfg = dict(config) if isinstance(config, Mapping) else {}
    cfg.pop("overrides", None)
    return cfg


def remap_ids(graph: Mapping[str, Any], operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Give added nodes and edges real ids and rewrite every reference to them."""
    node_ids = {str(n["id"]) for n in graph.get("nodes") or []}
    edge_ids = {str(e["id"]) for e in graph.get("edges") or []}
    mapping: dict[str, str] = {}
    ops = [copy.deepcopy(dict(op)) for op in operations if isinstance(op, Mapping)]
    for op in ops:
        if op.get("op") == "add_node" and isinstance(op.get("node"), dict):
            old = str(op["node"].get("id") or f"tmp_{len(mapping)}")
            if old in node_ids or old not in mapping:
                new = short_id("n")
                while new in node_ids:
                    new = short_id("n")
                mapping[old] = new
                node_ids.add(new)
            op["node"]["id"] = mapping[old]
        elif op.get("op") == "add_edge" and isinstance(op.get("edge"), dict):
            new = short_id("e")
            while new in edge_ids:
                new = short_id("e")
            edge_ids.add(new)
            op["edge"]["id"] = new

    def fix(value: Any) -> Any:
        return mapping.get(str(value), value) if value is not None else None

    for op in ops:
        if op.get("op") == "add_edge" and isinstance(op.get("edge"), dict):
            op["edge"]["source"] = fix(op["edge"].get("source"))
            op["edge"]["target"] = fix(op["edge"].get("target"))
        elif op.get("op") in ("update_node", "remove_node"):
            op["node_id"] = fix(op.get("node_id"))
        elif (
            op.get("op") == "update_edge"
            and isinstance(op.get("changes"), dict)
            and "target" in op["changes"]
        ):
            op["changes"]["target"] = fix(op["changes"]["target"])
    return ops


def apply_operations(
    graph: Mapping[str, Any], operations: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    """Apply remapped operations to a copy. Returns (graph, operations as applied, new name).

    ``remove_node`` also removes its connections, listed as ``remove_edge`` operations. An
    operation on an unknown id raises :class:`UnknownReference`.
    """
    out = copy.deepcopy(dict(graph))
    nodes: list[dict[str, Any]] = out.setdefault("nodes", [])
    edges: list[dict[str, Any]] = out.setdefault("edges", [])
    applied: list[dict[str, Any]] = []
    name: str | None = None

    def node(nid: Any) -> dict[str, Any]:
        found = next((n for n in nodes if n["id"] == nid), None)
        if found is None:
            raise UnknownReference(f"node {nid}")
        return found

    def edge(eid: Any) -> dict[str, Any]:
        found = next((e for e in edges if e["id"] == eid), None)
        if found is None:
            raise UnknownReference(f"edge {eid}")
        return found

    for raw in operations:
        op = copy.deepcopy(dict(raw))
        kind = op.get("op")
        if kind == "add_node":
            spec = op.get("node") or {}
            ntype = spec.get("type")
            if ntype not in NODE_TYPES:
                raise UnknownReference(f"node type {ntype}")
            new = {
                "id": spec["id"],
                "type": ntype,
                "label": str(spec.get("label") or DEFAULT_LABELS[str(ntype)])[:80],
                "position": spec.get("position") or {"x": 0, "y": 0},
                "config": config_with_defaults(str(ntype), _strip_overrides(spec.get("config"))),
                "_added": True,
            }
            nodes.append(new)
            applied.append({"op": "add_node", "node": {k: v for k, v in new.items() if k != "_added"}})
        elif kind == "update_node":
            target = node(op.get("node_id"))
            changes = op.get("changes") or {}
            clean: dict[str, Any] = {}
            if isinstance(changes.get("label"), str) and changes["label"].strip():
                target["label"] = clean["label"] = changes["label"].strip()[:80]
            if isinstance(changes.get("config"), Mapping):
                patch = _strip_overrides(changes["config"])
                target["config"] = agents.deep_merge(dict(target.get("config") or {}), patch)
                clean["config"] = patch
            applied.append({"op": "update_node", "node_id": target["id"], "changes": clean})
        elif kind == "remove_node":
            target = node(op.get("node_id"))
            for e in [e for e in edges if target["id"] in (e.get("source"), e.get("target"))]:
                edges.remove(e)
                applied.append({"op": "remove_edge", "edge_id": e["id"]})
            nodes.remove(target)
            applied.append({"op": "remove_node", "node_id": target["id"]})
        elif kind == "add_edge":
            spec = op.get("edge") or {}
            node(spec.get("source"))
            node(spec.get("target"))
            siblings = [e for e in edges if e.get("source") == spec.get("source")]
            new_edge = {
                "id": spec["id"],
                "source": spec["source"],
                "target": spec["target"],
                "trigger": spec.get("trigger") or "llm_condition",
                "label": spec.get("label"),
                "condition": spec.get("condition"),
                "category": spec.get("category"),
                "rule": spec.get("rule"),
                "sort_order": int(spec.get("sort_order") or len(siblings)),
            }
            new_edge = {k: v for k, v in new_edge.items() if v is not None}
            edges.append(new_edge)
            applied.append({"op": "add_edge", "edge": new_edge})
        elif kind == "update_edge":
            target_edge = edge(op.get("edge_id"))
            changes = {k: v for k, v in (op.get("changes") or {}).items() if k in EDGE_CHANGE_KEYS}
            if "target" in changes:
                node(changes["target"])
            target_edge.update(changes)
            applied.append({"op": "update_edge", "edge_id": target_edge["id"], "changes": changes})
        elif kind == "remove_edge":
            target_edge = edge(op.get("edge_id"))
            edges.remove(target_edge)
            applied.append({"op": "remove_edge", "edge_id": target_edge["id"]})
        elif kind == "rename_flow":
            name = str(op.get("name") or "").strip()[:NAME_MAX] or None
            if name:
                applied.append({"op": "rename_flow", "name": name})
    return out, applied, name


# Placement (FR-049) ---------------------------------------------------------------------------


def _overlaps(x: float, y: float, others: Sequence[Mapping[str, Any]]) -> bool:
    for o in others:
        pos = o.get("position") or {}
        ox, oy = float(pos.get("x", 0)), float(pos.get("y", 0))
        if x < ox + NODE_W and ox < x + NODE_W and y < oy + NODE_H and oy < y + NODE_H:
            return True
    return False


def place_added(graph: dict[str, Any], removed_edges: Sequence[Mapping[str, Any]]) -> None:
    """Position added nodes next to their neighbours without overlap; existing nodes stay put."""
    nodes: list[dict[str, Any]] = graph.get("nodes") or []
    edges = graph.get("edges") or []
    placed = [n for n in nodes if not n.get("_added")]
    by_id = {n["id"]: n for n in nodes}
    for n in [n for n in nodes if n.get("_added")]:
        ins = [
            str(e["source"])
            for e in edges
            if e.get("target") == n["id"] and not by_id[str(e["source"])].get("_added")
        ]
        outs = [
            str(e["target"])
            for e in edges
            if e.get("source") == n["id"] and not by_id[str(e["target"])].get("_added")
        ]
        between = next(
            (
                (by_id[str(r["source"])], by_id[str(r["target"])])
                for r in removed_edges
                if str(r.get("source")) in ins and str(r.get("target")) in outs
            ),
            None,
        )
        if between is not None:
            a, b = (p["position"] for p in between)
            x, y = (float(a["x"]) + float(b["x"])) / 2, (float(a["y"]) + float(b["y"])) / 2
        else:
            neighbour_id = next(iter(ins + outs), None)
            anchor = by_id.get(neighbour_id) if neighbour_id else None
            if anchor is None or anchor.get("_added"):
                anchor = max(placed, key=lambda p: float(p["position"]["x"]), default=None)
            if anchor is None:
                x, y = 0.0, 0.0
            else:
                ax, ay = float(anchor["position"]["x"]), float(anchor["position"]["y"])
                x, y = (
                    (ax + NODE_W + RANKSEP, ay) if neighbour_id not in outs else (ax - NODE_W - RANKSEP, ay)
                )
        while _overlaps(x, y, placed):
            y += STEP_Y
        n["position"] = {"x": round(x), "y": round(y)}
        placed.append(n)
    for n in nodes:
        n.pop("_added", None)


# Model answer ---------------------------------------------------------------------------------


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_answer(text: str) -> tuple[str, str | None, list[dict[str, Any]]]:
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except ValueError:
        return "I could not turn that into changes. Try describing the step you want.", None, []
    if not isinstance(data, dict):
        return "I could not turn that into changes. Try describing the step you want.", None, []
    message = str(data.get("message") or "Here are the changes.")
    name = data.get("flow_name")
    ops = [op for op in data.get("operations") or [] if isinstance(op, dict)]
    return message, name if isinstance(name, str) and name.strip() else None, ops


def build_system(graph: Mapping[str, Any], persona: str, name: str) -> str:
    compact = {
        "nodes": [
            {
                "id": n["id"],
                "type": n["type"],
                "label": n["label"],
                "position": n.get("position"),
                "config": _strip_overrides(n.get("config")),
            }
            for n in graph.get("nodes") or []
        ],
        "edges": graph.get("edges") or [],
    }
    return "\n".join(
        [
            SYSTEM_PROMPT,
            f"\nFlow name: {name}",
            f"<persona_prompt>\n{persona}\n</persona_prompt>",
            f"<graph>\n{json.dumps(compact, separators=(',', ':'))}\n</graph>",
        ]
    )


async def ask(
    db: Database,
    settings: Settings,
    client: LlmClient,
    *,
    workspace_id: str,
    user_id: str | None,
    flow_id: str,
    request: AssistantRequest,
) -> dict[str, Any]:
    with tracer.start_as_current_span("flows.assistant") as span:
        async with db.transaction(workspace_id=workspace_id) as session:
            flow = await service.get_flow(session, flow_id)
            if request.base_revision != flow.revision:
                raise service.flow_revision_conflict(flow.revision, status=409)
            agent = await agents.get_agent(session, flow.agent_id)
            graph = (
                request.graph.model_dump(mode="json")
                if request.graph is not None
                else copy.deepcopy(flow.graph)
            )
            if await billing.get_balance(session, workspace_id) <= 0:
                raise billing.insufficient_credit("Add funds to use the flow assistant.")
            ctx = await service.context_for(session, agent)
            system = build_system(graph, str(agent.draft_config.get("prompt") or ""), flow.name)
        model_ref = ModelRef.parse(model_for(settings))
        span.set_attribute("llm.model", f"{model_ref.provider}/{model_ref.model}")
        try:
            completion = await client.complete(
                model_ref,
                [ChatMessage(m.role, m.content) for m in request.messages],
                system=system,
                max_tokens=MAX_OUTPUT_TOKENS,
                timeout_s=settings.flow_assistant_timeout_s,
                json_mode=True,
                purpose="flow_assistant",
            )
        except (ModelTimeout, ModelError) as exc:
            span.record_exception(exc)
            raise assistant_timeout() from exc

        message, name, raw_ops = parse_answer(completion.text)
        try:
            ops = remap_ids(graph, raw_ops)
            proposed, applied, renamed = apply_operations(graph, ops)
            removed = [
                e
                for e in graph.get("edges") or []
                if e["id"] in {o["edge_id"] for o in applied if o["op"] == "remove_edge"}
            ]
            place_added(proposed, removed)
            FlowGraph.model_validate(proposed)
        except (UnknownReference, ValueError, KeyError, TypeError) as exc:
            span.record_exception(exc)
            message = (
                "The assistant referred to steps that are not in this flow. Ask again and it will "
                "start from the current canvas."
            )
            proposed, applied, renamed = copy.deepcopy(graph), [], None
        issues = validation.validate(proposed, ctx.validation)
        for op in applied:  # positions are final only after placement
            if op["op"] == "add_node":
                op["node"]["position"] = next(
                    n["position"] for n in proposed["nodes"] if n["id"] == op["node"]["id"]
                )

        raw = token_cost(model_ref.model, completion.input_tokens, completion.output_tokens)
        billable = billable_cost(raw)
        async with db.transaction(workspace_id=workspace_id) as session:
            await billing.charge_feature(
                session,
                workspace_id=workspace_id,
                feature_key="flow_assistant",
                quantity=Decimal(completion.input_tokens + completion.output_tokens),
                unit="tokens",
                raw_cost_usd=raw.quantize(Decimal("0.000001")),
                billable_cost_usd=billable,
                idempotency_key=f"flow_assistant:{uuid.uuid4().hex}",
                ref_type="agent",
                ref_id=flow.agent_id,
            )
        return {
            "message": message,
            "flow_name": renamed or name,
            "operations": applied,
            "proposed_graph": proposed,
            "issues": issues,
            "base_revision": request.base_revision,
            "usage": {
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
                "cost_usd": fmt6(billable),
            },
        }
