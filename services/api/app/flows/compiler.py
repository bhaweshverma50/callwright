"""Graph to CompiledFlow (T039, T077; data-model section 4, research R8, R9).

The compiled flow is self-contained: every conversational node carries its resolved model,
voice, speech recognition and language (node override or the agent default), its instructions
with the persona prompt prepended, full tool definitions (005 snapshot form, secrets as refs
only), knowledge search settings and its transitions. The worker needs nothing else to run it.

``graph_hash`` is SHA-256 over the canonical graph without positions and the viewport, so a
layout-only change keeps the same hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.flows import transitions
from app.flows.schemas import CONVERSATIONAL
from app.flows.starter import config_with_defaults
from app.flows.variables import BUILTIN_VARIABLES, TASK_RESULT
from app.llms.service import load_catalog as load_llm_catalog

SCHEMA_VERSION = 1


def canonical_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    nodes = [
        {"id": n.get("id"), "type": n.get("type"), "label": n.get("label"), "config": n.get("config") or {}}
        for n in graph.get("nodes") or []
    ]
    edges = [{k: v for k, v in e.items() if v is not None} for e in graph.get("edges") or []]
    return {"nodes": nodes, "edges": edges}


def graph_hash(graph: Mapping[str, Any]) -> str:
    text = json.dumps(canonical_graph(graph), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(section: Any) -> dict[str, Any]:
    return {k: v for k, v in section.items() if v is not None} if isinstance(section, Mapping) else {}


def resolve_llm(agent: Mapping[str, Any], override: Any) -> dict[str, Any]:
    base = dict(agent.get("llm") or {})
    ov = _clean(override)
    if not ov:
        return {
            "provider": base.get("provider"),
            "model": base.get("model"),
            "temperature": base.get("temperature"),
        }
    provider = ov.get("provider", base.get("provider"))
    model_id = ov.get("model", base.get("model"))
    temperature = ov.get("temperature")
    if temperature is None:
        same = provider == base.get("provider") and model_id == base.get("model")
        model = load_llm_catalog().model(str(provider), str(model_id))
        temperature = base.get("temperature") if same or model is None else model.temperature.default_value
    model = load_llm_catalog().model(str(provider), str(model_id))
    if model is not None and model.temperature.is_fixed:
        temperature = model.temperature.fixed
    return {"provider": provider, "model": model_id, "temperature": temperature}


def resolve_tts(agent: Mapping[str, Any], override: Any) -> dict[str, Any]:
    base = dict(agent.get("tts") or {})
    ov = _clean(override)
    if ov.get("provider") and ov["provider"] != base.get("provider"):
        # A different provider never inherits the old provider's model or voice (FR-054).
        base = {k: v for k, v in base.items() if k not in ("model", "voice_id")}
    base.update(ov)
    return base


def resolve_stt(agent: Mapping[str, Any], override: Any, language: str) -> dict[str, Any]:
    base = dict(agent.get("stt") or {})
    ov = _clean(override)
    if ov:
        if ov.get("provider") and ov["provider"] != base.get("provider"):
            base = {"provider": ov["provider"], "model": None}
        base.update(ov)
    elif language != agent.get("language"):
        base["model"] = None  # Auto: the worker resolves a model for the node language
    return {"provider": base.get("provider"), "model": base.get("model")}


def task_schema(fields: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for f in fields:
        name = str(f.get("name"))
        prop: dict[str, Any] = {"description": str(f.get("description") or "")}
        ftype = f.get("type")
        if ftype == "enum":
            prop.update({"type": "string", "enum": [str(v) for v in f.get("enum_values") or []]})
        else:
            prop["type"] = ftype if ftype in ("string", "number", "boolean") else "string"
        props[name] = prop
        if f.get("required", True):
            required.append(name)
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def declared_variables(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for n in nodes:
        cfg = n.get("config") or {}
        nid = str(n.get("id"))
        if n.get("type") == "extract_variable":
            out += [
                {"name": str(f.get("name")), "source_node_id": nid, "type": str(f.get("type"))}
                for f in cfg.get("fields") or []
            ]
        elif n.get("type") == "task":
            out += [
                {"name": f"{TASK_RESULT}.{f.get('name')}", "source_node_id": nid, "type": str(f.get("type"))}
                for f in cfg.get("fields") or []
            ]
        elif n.get("type") == "webhook":
            for m in (cfg.get("request") or {}).get("response_mappings") or []:
                out.append({"name": str(m.get("variable_name")), "source_node_id": nid, "type": "string"})
    return out


def compile_flow(
    flow_id: str,
    graph: Mapping[str, Any],
    agent_config: Mapping[str, Any],
    tool_specs: Mapping[str, Mapping[str, Any]],
    *,
    compiled_at: datetime | None = None,
) -> dict[str, Any]:
    """Compile a graph that validated without errors. ``tool_specs`` maps tool ids to their
    snapshot form (``tools.service.resolve_for_snapshot``) for node and flow-level tools."""
    nodes = list(graph.get("nodes") or [])
    by_id = {str(n["id"]): n for n in nodes}
    edges = sorted(graph.get("edges") or [], key=lambda e: int(e.get("sort_order") or 0))
    outgoing: dict[str, list[Mapping[str, Any]]] = {nid: [] for nid in by_id}
    for e in edges:
        if e.get("source") in outgoing and e.get("target") in by_id:
            outgoing[str(e["source"])].append(e)

    def first(nid: str, trigger: str) -> str | None:
        return next((str(e["target"]) for e in outgoing[nid] if e.get("trigger") == trigger), None)

    persona = str(agent_config.get("prompt") or "")
    language_default = str(agent_config.get("language") or "en-US")
    flow_tool_ids = [str(t) for t in agent_config.get("tool_ids") or []]
    kb_ids = [str(k) for k in agent_config.get("kb_ids") or []]
    entry = next(str(n["id"]) for n in nodes if n.get("type") == "start")
    compiled_nodes: dict[str, Any] = {}

    for n in nodes:
        nid, ntype = str(n["id"]), str(n["type"])
        cfg = config_with_defaults(ntype, n.get("config"))
        out: dict[str, Any] = {"type": ntype, "label": n.get("label")}
        if ntype in CONVERSATIONAL:
            overrides = cfg.get("overrides") or {}
            language = str(overrides.get("language") or language_default)
            instructions = "\n\n".join(
                p for p in (persona.strip(), str(cfg.get("instructions") or "").strip()) if p
            )
            ids = list(dict.fromkeys([*[str(t) for t in cfg.get("tool_ids") or []], *flow_tool_ids]))
            begin = cfg.get("begin_message")
            out.update(
                {
                    "instructions": instructions,
                    "begin_message": begin.strip() if isinstance(begin, str) and begin.strip() else None,
                    "context_strategy": cfg.get("context_strategy") or "inherit",
                    "llm": resolve_llm(agent_config, overrides.get("llm")),
                    "tts": resolve_tts(agent_config, overrides.get("tts")),
                    "stt": resolve_stt(agent_config, overrides.get("stt"), language),
                    "language": language,
                    "tools": [copy.deepcopy(dict(tool_specs[t])) for t in ids if t in tool_specs],
                    "kb_search": {
                        "enabled": bool(cfg.get("kb_search_enabled", True) and kb_ids),
                        "kb_ids": kb_ids,
                    },
                    "transitions": [
                        {
                            "edge_id": e["id"],
                            "function_name": transitions.function_name(
                                e.get("label"), e.get("function_name")
                            ),
                            "description": transitions.description(
                                str(by_id[str(e["target"])].get("label")), e.get("condition")
                            ),
                            "target_node_id": e["target"],
                            "trigger": "llm_condition",
                            "label": e.get("label"),
                        }
                        for e in outgoing[nid]
                        if e.get("trigger") == "llm_condition"
                    ],
                    "task": None,
                }
            )
            if ntype == "task":
                out["task"] = {
                    "json_schema": task_schema(cfg.get("fields") or []),
                    "max_rounds": int(cfg.get("max_rounds") or 5),
                    "success_target": first(nid, "success"),
                    "success_edge_id": next(
                        (e["id"] for e in outgoing[nid] if e.get("trigger") == "success"), None
                    ),
                }
        elif ntype == "start":
            nxt = outgoing[nid][0] if outgoing[nid] else None
            out["start"] = {
                "start_speaker": cfg.get("start_speaker") or "agent",
                "greeting_type": cfg.get("greeting_type") or "static",
                "greeting": str(cfg.get("greeting") or ""),
                "next": nxt["target"] if nxt else None,
                "edge_id": nxt["id"] if nxt else None,
            }
        elif ntype == "say":
            nxt = outgoing[nid][0] if outgoing[nid] else None
            out["say"] = {
                "message": str(cfg.get("message") or ""),
                "allow_interruptions": bool(cfg.get("allow_interruptions", True)),
                "next": nxt["target"] if nxt else None,
                "edge_id": nxt["id"] if nxt else None,
            }
        elif ntype == "condition":
            kind = "rule" if cfg.get("kind") == "rule" else "classify"
            cats = []
            for c in cfg.get("categories") or [] if kind == "classify" else []:
                edge = next(
                    (
                        e
                        for e in outgoing[nid]
                        if e.get("trigger") == "category" and e.get("category") == c.get("name")
                    ),
                    None,
                )
                cats.append(
                    {
                        "name": c.get("name"),
                        "description": c.get("description") or "",
                        "target": edge["target"] if edge else None,
                        "edge_id": edge["id"] if edge else None,
                    }
                )
            rules = [
                {
                    "edge_id": e["id"],
                    "variable": str((e.get("rule") or {}).get("variable") or "").strip().strip("{} "),
                    "operator": (e.get("rule") or {}).get("operator"),
                    "value": (e.get("rule") or {}).get("value"),
                    "target": e["target"],
                    "label": e.get("label"),
                }
                for e in outgoing[nid]
                if kind == "rule" and e.get("trigger") == "rule"
            ]
            else_edge = next((e for e in outgoing[nid] if e.get("trigger") == "else"), None)
            out["condition"] = {
                "kind": kind,
                "instructions": str(cfg.get("instructions") or ""),
                "categories": cats,
                "rules": rules,
                "else_target": else_edge["target"] if else_edge else None,
                "else_edge_id": else_edge["id"] if else_edge else None,
            }
        elif ntype == "extract_variable":
            nxt = outgoing[nid][0] if outgoing[nid] else None
            fields = [dict(f, required=False) for f in cfg.get("fields") or []]
            out["extract"] = {
                "instructions": str(cfg.get("instructions") or ""),
                "json_schema": task_schema(fields),
                "next": nxt["target"] if nxt else None,
                "edge_id": nxt["id"] if nxt else None,
            }
        elif ntype == "webhook":
            ok = next((e for e in outgoing[nid] if e.get("trigger") == "success"), None)
            bad = next((e for e in outgoing[nid] if e.get("trigger") == "failure"), None)
            out["webhook"] = {
                "request": copy.deepcopy(cfg.get("request") or {}),
                "mock_response": cfg.get("mock_response"),
                "success_target": ok["target"] if ok else None,
                "success_edge_id": ok["id"] if ok else None,
                "failure_target": bad["target"] if bad else None,
                "failure_edge_id": bad["id"] if bad else None,
            }
        elif ntype == "transfer":
            bad = next((e for e in outgoing[nid] if e.get("trigger") == "failure"), None)
            out["transfer"] = {
                "transfer": copy.deepcopy(cfg.get("transfer") or {}),
                "failure_target": bad["target"] if bad else None,
                "failure_edge_id": bad["id"] if bad else None,
            }
        elif ntype == "end":
            out["end"] = {
                "message": str(cfg.get("message") or ""),
                "reason": str(cfg.get("reason") or "call_completed"),
            }
        compiled_nodes[nid] = out

    return {
        "schema_version": SCHEMA_VERSION,
        "flow_id": flow_id,
        "graph_hash": graph_hash(graph),
        "compiled_at": (compiled_at or datetime.now(UTC)).isoformat(),
        "entry_node_id": entry,
        "persona_prompt": persona,
        "builtin_variables": list(BUILTIN_VARIABLES),
        "declared_variables": declared_variables(nodes),
        "nodes": compiled_nodes,
    }


def tool_ids_in(graph: Mapping[str, Any], agent_config: Mapping[str, Any]) -> list[str]:
    ids: list[str] = [str(t) for t in agent_config.get("tool_ids") or []]
    for n in graph.get("nodes") or []:
        if n.get("type") in CONVERSATIONAL:
            ids += [str(t) for t in (n.get("config") or {}).get("tool_ids") or []]
    return list(dict.fromkeys(ids))
