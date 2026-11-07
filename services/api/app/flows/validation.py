"""Flow validation (T038, T078, T110; data-model sections 2.2 and 3, research R6).

One pass over the graph document, used by save, ``/validate``, compile and publish. Every issue
is ``{severity, code, message, node_id, edge_id, field}``. Order is stable: errors before
warnings, graph-level issues first, then by node order in ``graph.nodes``, then by edge order.

The graph may be any draft (incomplete configs, out-of-range numbers); nothing here raises.
References to the workspace's tools and the 002 catalogs are checked when the caller supplies
them in :class:`ValidationContext`.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from callwright_contract.values import COMPLETE_TASK_TOOL, E164
from callwright_contract.variables import BUILTIN_VARIABLES, DOTTED_PLACEHOLDER
from pydantic import ValidationError

from app.flows import transitions
from app.flows.compiled import TERMINAL_NODE_TYPES
from app.flows.schemas import CONVERSATIONAL, MAX_EDGES, MAX_NODES
from app.flows.variables import TASK_RESULT, placeholders
from app.tools.schemas import HttpRequestSpec, TransferSpec

Issue = dict[str, Any]
OverrideChecker = Callable[[Mapping[str, Any]], list[tuple[str, str, str]]]

MAX_INSTRUCTIONS = 16_000
MAX_PERSONA = 32_000
MAX_CATEGORIES = 20
MAX_RULES = 20
MAX_FIELDS = 30
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
CATEGORY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,59}$")
END_REASON = re.compile(r"^[a-z_]{1,40}$")
CONTEXT_STRATEGIES = ("inherit", "summarize", "reset")
TASK_FIELD_TYPES = ("string", "number", "boolean", "enum")
EXTRACT_FIELD_TYPES = ("string", "number", "boolean")

ALLOWED_TRIGGERS: dict[str, frozenset[str]] = {
    "start": frozenset({"always"}),
    "agent": frozenset({"llm_condition"}),
    "task": frozenset({"success", "llm_condition"}),
    "classify": frozenset({"category"}),
    "rule": frozenset({"rule", "else"}),
    "say": frozenset({"always"}),
    "extract_variable": frozenset({"always"}),
    "webhook": frozenset({"success", "failure"}),
    "transfer": frozenset({"failure"}),
    "end": frozenset(),
}
START_TARGETS = frozenset({"agent", "task", "say"})


@dataclass(frozen=True)
class ValidationContext:
    """What the validator may check beyond the graph itself.

    ``tools`` maps the workspace's tool ids to names (``None`` skips ``E_UNKNOWN_TOOL``);
    ``flow_tool_names`` are the names of tools attached at flow level (agent ``tool_ids``);
    ``check_overrides`` returns ``(code, field, message)`` for one node's overrides.
    """

    persona_prompt: str = ""
    defaulted_variables: frozenset[str] = frozenset()
    tools: Mapping[str, str] | None = None
    flow_tool_names: tuple[str, ...] = ()
    check_overrides: OverrideChecker | None = None
    allow_http_webhook: bool = False


@dataclass
class _Collector:
    node_index: dict[str, int]
    edge_index: dict[str, int]
    issues: list[tuple[tuple[int, int, int, int], Issue]] = field(default_factory=list)

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        edge_id: str | None = None,
        field_: str | None = None,
    ) -> None:
        if node_id is not None and node_id in self.node_index:
            place = (1, self.node_index[node_id])
        elif edge_id is not None and edge_id in self.edge_index:
            place = (2, self.edge_index[edge_id])
        else:
            place = (0, 0)
        key = (0 if severity == "error" else 1, place[0], place[1], len(self.issues))
        self.issues.append(
            (
                key,
                {
                    "severity": severity,
                    "code": code,
                    "message": message,
                    "node_id": node_id,
                    "edge_id": edge_id,
                    "field": field_,
                },
            )
        )

    def error(self, code: str, message: str, **kw: Any) -> None:
        self.add("error", code, message, **kw)

    def warn(self, code: str, message: str, **kw: Any) -> None:
        self.add("warning", code, message, **kw)

    def sorted(self) -> list[Issue]:
        return [issue for _, issue in sorted(self.issues, key=lambda pair: pair[0])]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _conf(node: Mapping[str, Any]) -> Mapping[str, Any]:
    cfg = node.get("config")
    return cfg if isinstance(cfg, Mapping) else {}


def _kind(node: Mapping[str, Any]) -> str:
    if node.get("type") == "condition":
        return "rule" if _conf(node).get("kind") == "rule" else "classify"
    return str(node.get("type"))


def _json_ok(text: str) -> bool:
    try:
        json.loads(DOTTED_PLACEHOLDER.sub("0", text))
    except ValueError:
        return False
    return True


def _pydantic_field(exc: ValidationError) -> tuple[str, str]:
    """The first failing field of a 005 model and its message."""
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
    if ": " in msg and not loc:
        loc, _, msg = msg.partition(": ")
    return loc, msg


def validate(graph: Mapping[str, Any], ctx: ValidationContext | None = None) -> list[Issue]:
    ctx = ctx or ValidationContext()
    nodes: list[Mapping[str, Any]] = [n for n in graph.get("nodes") or [] if isinstance(n, Mapping)]
    edges: list[Mapping[str, Any]] = [e for e in graph.get("edges") or [] if isinstance(e, Mapping)]
    by_id = {str(n.get("id")): n for n in nodes}
    out = _Collector(
        {str(n.get("id")): i for i, n in enumerate(nodes)}, {str(e.get("id")): i for i, e in enumerate(edges)}
    )

    # Limits ----------------------------------------------------------------------------------
    if len(nodes) > MAX_NODES:
        out.error("E_LIMIT", f"A flow can have at most {MAX_NODES} nodes.")
    if len(edges) > MAX_EDGES:
        out.error("E_LIMIT", f"A flow can have at most {MAX_EDGES} connections.")
    if len(ctx.persona_prompt) > MAX_PERSONA:
        out.error("E_LIMIT", f"The persona prompt can be at most {MAX_PERSONA:,} characters.")

    # Start count -------------------------------------------------------------------------------
    starts = [n for n in nodes if n.get("type") == "start"]
    if not starts:
        out.error("E_START_COUNT", "A flow needs exactly one Start node.")
    for extra in starts[1:]:
        out.error("E_START_COUNT", "A flow needs exactly one Start node.", node_id=str(extra.get("id")))

    # Edges: endpoints, then grouping by source -------------------------------------------------
    live: list[Mapping[str, Any]] = []
    for e in edges:
        if e.get("source") not in by_id or e.get("target") not in by_id:
            out.error(
                "E_DANGLING_EDGE",
                "This connection points to a node that no longer exists. Remove it.",
                edge_id=str(e.get("id")),
            )
        else:
            live.append(e)
    outgoing: dict[str, list[Mapping[str, Any]]] = {nid: [] for nid in by_id}
    incoming: dict[str, list[Mapping[str, Any]]] = {nid: [] for nid in by_id}
    for e in sorted(live, key=lambda e: int(e.get("sort_order") or 0)):
        outgoing[str(e["source"])].append(e)
        incoming[str(e["target"])].append(e)

    tool_names = ctx.tools or {}
    set_variables = set(BUILTIN_VARIABLES) | set(ctx.defaulted_variables)
    extract_names: dict[str, str] = {}
    for n in nodes:
        cfg = _conf(n)
        if n.get("type") == "extract_variable":
            for f in cfg.get("fields") or []:
                if isinstance(f, Mapping) and isinstance(f.get("name"), str):
                    set_variables.add(f["name"])
        elif n.get("type") == "task":
            for f in cfg.get("fields") or []:
                if isinstance(f, Mapping) and isinstance(f.get("name"), str):
                    set_variables.add(f"{TASK_RESULT}.{f['name']}")
        elif n.get("type") == "webhook":
            req = cfg.get("request")
            request: Mapping[str, Any] = req if isinstance(req, Mapping) else {}
            for m in request.get("response_mappings") or []:
                if isinstance(m, Mapping) and isinstance(m.get("variable_name"), str):
                    set_variables.add(m["variable_name"])

    for n in nodes:
        nid = str(n.get("id"))
        ntype = str(n.get("type"))
        kind = _kind(n)
        cfg = _conf(n)
        outs = outgoing.get(nid, [])
        label = str(n.get("label") or ntype)

        for e in outs:
            if e.get("trigger") not in ALLOWED_TRIGGERS.get(kind, frozenset()):
                where = "a Start node" if ntype == "start" else f"this {kind.replace('_', ' ')} node"
                out.error(
                    "E_TRIGGER_NOT_ALLOWED",
                    f"A {e.get('trigger')} connection cannot leave {where}.",
                    edge_id=str(e.get("id")),
                )
        allowed = [e for e in outs if e.get("trigger") in ALLOWED_TRIGGERS.get(kind, frozenset())]
        by_trigger: dict[str, list[Mapping[str, Any]]] = {}
        for e in allowed:
            by_trigger.setdefault(str(e.get("trigger")), []).append(e)

        texts: list[str] = []
        if ntype == "start":
            _check_start(out, n, cfg, outs, incoming.get(nid, []), by_id)
            texts.append(_text(cfg.get("greeting")))
        elif ntype in CONVERSATIONAL:
            texts += _check_conversational(
                out, n, cfg, ctx, tool_names, by_trigger, incoming.get(nid, []), by_id
            )
        elif ntype == "condition":
            texts.append(_text(cfg.get("instructions")))
            _check_condition(out, n, cfg, kind, outs, by_trigger, set_variables)
        elif ntype == "say":
            message = _text(cfg.get("message"))
            texts.append(message)
            if not message.strip():
                out.error(
                    "E_REQUIRED_FIELD", "Write the message this node says.", node_id=nid, field_="message"
                )
            elif len(message) > 1000:
                out.error(
                    "E_INVALID_FIELD",
                    "The message can be at most 1,000 characters.",
                    node_id=nid,
                    field_="message",
                )
            _exactly_one(out, nid, label, outs, by_trigger, "always")
        elif ntype == "extract_variable":
            texts.append(_text(cfg.get("instructions")))
            _check_extract(out, nid, cfg, extract_names)
            _exactly_one(out, nid, label, outs, by_trigger, "always")
        elif ntype == "webhook":
            texts += _check_webhook(out, nid, cfg, ctx)
            if not outs:
                out.error("E_MISSING_OUTGOING", f"Connect {label} to the next step.", node_id=nid)
            elif len(by_trigger.get("success", [])) != 1:
                out.error(
                    "E_EDGE_CARDINALITY",
                    "An API call node needs exactly one success connection.",
                    node_id=nid,
                )
            if len(by_trigger.get("failure", [])) > 1:
                out.error(
                    "E_EDGE_CARDINALITY",
                    "An API call node can have at most one failure connection.",
                    node_id=nid,
                )
        elif ntype == "transfer":
            texts += _check_transfer(out, nid, cfg)
            failures = by_trigger.get("failure", [])
            if len(failures) > 1:
                out.error(
                    "E_EDGE_CARDINALITY",
                    "A transfer node can have at most one failure connection.",
                    node_id=nid,
                )
            elif not failures:
                out.warn(
                    "W_TRANSFER_NO_FALLBACK",
                    "If the transfer fails the call stays here. Add a failure connection.",
                    node_id=nid,
                )
        elif ntype == "end":
            message = _text(cfg.get("message"))
            texts.append(message)
            if outs:
                out.error("E_END_HAS_EDGES", "An End node cannot have outgoing connections.", node_id=nid)
            # An empty message is fine: the agent says a goodbye that fits the call.
            if len(message) > 500:
                out.error(
                    "E_INVALID_FIELD",
                    "The closing message can be at most 500 characters.",
                    node_id=nid,
                    field_="message",
                )
            reason = cfg.get("reason", "call_completed")
            if not isinstance(reason, str) or not END_REASON.match(reason):
                out.error(
                    "E_INVALID_FIELD",
                    "Use lowercase letters and underscores for the end reason.",
                    node_id=nid,
                    field_="reason",
                )

        for used in dict.fromkeys(v for t in texts for v in placeholders(t)):
            if used not in set_variables:
                out.warn(
                    "W_UNSET_VARIABLE",
                    f"{{{{{used}}}}} is never set by an earlier step and has no default; it will be empty.",
                    node_id=nid,
                )

    # Transitions leaving conversational nodes ---------------------------------------------------
    for n in nodes:
        if n.get("type") not in CONVERSATIONAL:
            continue
        nid = str(n.get("id"))
        cfg = _conf(n)
        attached = [tool_names[t] for t in cfg.get("tool_ids") or [] if t in tool_names]
        taken: dict[str, str] = {name: "tool" for name in [*attached, *ctx.flow_tool_names]}
        if n.get("type") == "task":
            taken[COMPLETE_TASK_TOOL] = "tool"
        for e in outgoing.get(nid, []):
            if e.get("trigger") != "llm_condition":
                continue
            eid = str(e.get("id"))
            lbl = e.get("label")
            if not isinstance(lbl, str) or not lbl.strip():
                out.error(
                    "E_REQUIRED_FIELD", "Give this connection a short label.", edge_id=eid, field_="label"
                )
                name: str | None = e.get("function_name") or None
            else:
                name = transitions.function_name(lbl, e.get("function_name"))
                if name is None:
                    out.error(
                        "E_TRANSITION_NAME_EMPTY",
                        "The label needs at least one letter or digit.",
                        edge_id=eid,
                        field_="label",
                    )
            if not _text(e.get("condition")).strip():
                out.error(
                    "E_REQUIRED_FIELD",
                    "Describe when the agent should take this connection.",
                    edge_id=eid,
                    field_="condition",
                )
            if name:
                if name in taken:
                    clash = "a tool on this node" if taken[name] == "tool" else "another connection"
                    out.error(
                        "E_FUNCTION_NAME_CLASH",
                        f"This connection's name {name} is the same as {clash}. Rename one of them.",
                        edge_id=eid,
                        field_="label",
                    )
                else:
                    taken[name] = "edge"

    # Reachability -------------------------------------------------------------------------------
    if len(starts) >= 1:
        start_id = str(starts[0].get("id"))
        reached = _bfs(start_id, {k: [str(e["target"]) for e in v] for k, v in outgoing.items()})
        for n in nodes:
            nid = str(n.get("id"))
            if nid not in reached and n.get("type") != "start":
                out.warn("W_UNREACHABLE", "No path from Start reaches this node.", node_id=nid)
        exits = [str(n.get("id")) for n in nodes if n.get("type") in TERMINAL_NODE_TYPES]
        reverse = {k: [str(e["source"]) for e in v] for k, v in incoming.items()}
        can_exit: set[str] = set()
        for x in exits:
            can_exit |= _bfs(x, reverse)
        stuck = [
            str(n.get("id"))
            for n in nodes
            if str(n.get("id")) in reached and str(n.get("id")) not in can_exit
        ]
        if stuck:
            out.warn(
                "W_NO_EXIT",
                "Calls that reach this part of the flow can only end by hang-up or time limit.",
                node_id=stuck[0],
            )

    return out.sorted()


def _bfs(start: str, adjacency: Mapping[str, Sequence[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        for nxt in adjacency.get(queue.popleft(), []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _exactly_one(
    out: _Collector,
    nid: str,
    label: str,
    outs: Sequence[Mapping[str, Any]],
    by_trigger: Mapping[str, Sequence[Mapping[str, Any]]],
    trigger: str,
) -> None:
    if not outs:
        out.error("E_MISSING_OUTGOING", f"Connect {label} to the next step.", node_id=nid)
    elif len(by_trigger.get(trigger, [])) != 1:
        out.error("E_EDGE_CARDINALITY", "This node needs exactly one outgoing connection.", node_id=nid)


def _check_start(
    out: _Collector,
    n: Mapping[str, Any],
    cfg: Mapping[str, Any],
    outs: Sequence[Mapping[str, Any]],
    ins: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    nid = str(n.get("id"))
    if ins:
        out.error("E_START_EDGES", "Nothing can connect into the Start node.", node_id=nid)
    if len(outs) != 1:
        out.error("E_START_EDGES", "Start needs exactly one connection to the first step.", node_id=nid)
    target_type = str(by_id[str(outs[0]["target"])].get("type")) if len(outs) == 1 else None
    if target_type is not None and target_type not in START_TARGETS:
        out.error("E_START_EDGES", "Start must lead to an Agent, Task or Say node.", node_id=nid)
    speaker = cfg.get("start_speaker", "agent")
    greeting_type = cfg.get("greeting_type", "static")
    greeting = _text(cfg.get("greeting"))
    if speaker not in ("agent", "user"):
        out.error("E_INVALID_FIELD", "Choose who speaks first.", node_id=nid, field_="start_speaker")
    if greeting_type not in ("static", "generated"):
        out.error("E_INVALID_FIELD", "Choose a greeting kind.", node_id=nid, field_="greeting_type")
    if len(greeting) > 500:
        out.error(
            "E_INVALID_FIELD", "The greeting can be at most 500 characters.", node_id=nid, field_="greeting"
        )
    if speaker == "agent" and greeting_type == "static" and not greeting.strip():
        out.error(
            "E_REQUIRED_FIELD",
            "Write the greeting the agent opens the call with.",
            node_id=nid,
            field_="greeting",
        )
    if speaker == "agent" and greeting_type == "generated" and target_type not in (None, "agent", "task"):
        out.error(
            "E_GREETING_SOURCE",
            "A model-written greeting comes from the first Agent or Task node. Connect Start to one, "
            "or use a fixed greeting.",
            node_id=nid,
            field_="greeting_type",
        )


def _check_conversational(
    out: _Collector,
    n: Mapping[str, Any],
    cfg: Mapping[str, Any],
    ctx: ValidationContext,
    tool_names: Mapping[str, str],
    by_trigger: Mapping[str, Sequence[Mapping[str, Any]]],
    ins: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    nid = str(n.get("id"))
    ntype = str(n.get("type"))
    instructions = _text(cfg.get("instructions"))
    begin = cfg.get("begin_message")
    if len(instructions) > MAX_INSTRUCTIONS:
        out.error(
            "E_LIMIT",
            f"Instructions can be at most {MAX_INSTRUCTIONS:,} characters.",
            node_id=nid,
            field_="instructions",
        )
    if not instructions.strip() and not ctx.persona_prompt.strip():
        out.warn(
            "W_NO_INSTRUCTIONS",
            "This node has no instructions and the flow has no persona prompt.",
            node_id=nid,
            field_="instructions",
        )
    if isinstance(begin, str) and len(begin) > 500:
        out.error(
            "E_INVALID_FIELD",
            "The entry line can be at most 500 characters.",
            node_id=nid,
            field_="begin_message",
        )
    if cfg.get("context_strategy", "inherit") not in CONTEXT_STRATEGIES:
        out.error(
            "E_INVALID_FIELD",
            "Choose how much of the conversation this node sees.",
            node_id=nid,
            field_="context_strategy",
        )
    tool_ids = cfg.get("tool_ids") or []
    if ctx.tools is not None:
        for i, tid in enumerate(tool_ids):
            if tid not in tool_names:
                out.error(
                    "E_UNKNOWN_TOOL",
                    "This tool no longer exists. Remove it.",
                    node_id=nid,
                    field_=f"tool_ids.{i}",
                )
        names = [tool_names[t] for t in tool_ids if t in tool_names]
        for dup in sorted({x for x in names if names.count(x) > 1 or x in ctx.flow_tool_names}):
            out.error(
                "E_FUNCTION_NAME_CLASH", f"The tool {dup} is attached twice.", node_id=nid, field_="tool_ids"
            )
    overrides = cfg.get("overrides")
    if isinstance(overrides, Mapping) and ctx.check_overrides is not None:
        for code, field_, message in ctx.check_overrides(overrides):
            out.error(code, message, node_id=nid, field_=f"overrides.{field_}")
    if ntype == "task":
        _check_task(out, nid, cfg)
        if len(by_trigger.get("success", [])) != 1:
            out.error(
                "E_EDGE_CARDINALITY",
                "A Task node needs exactly one success connection for when the details are collected.",
                node_id=nid,
            )
    elif not by_trigger.get("llm_condition"):
        out.warn("W_NODE_STALLS", "The call will stay in this node. Add a connection out of it.", node_id=nid)
    entered_mid_call = any(str(by_id[str(e["source"])].get("type")) not in ("start", "say") for e in ins)
    if entered_mid_call and not (isinstance(begin, str) and begin.strip()):
        out.warn(
            "W_NO_BEGIN_MESSAGE",
            "Add an entry line so the agent answers at once when the call moves here.",
            node_id=nid,
            field_="begin_message",
        )
    return [instructions, _text(begin)]


def _check_task(out: _Collector, nid: str, cfg: Mapping[str, Any]) -> None:
    rounds = cfg.get("max_rounds", 5)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 20:
        out.error(
            "E_INVALID_FIELD",
            "Max rounds must be a whole number from 1 to 20.",
            node_id=nid,
            field_="max_rounds",
        )
    fields = cfg.get("fields")
    if not isinstance(fields, list) or not fields:
        out.error("E_INVALID_SCHEMA", "Add at least one field to collect.", node_id=nid, field_="fields")
        return
    if len(fields) > MAX_FIELDS:
        out.error(
            "E_INVALID_SCHEMA",
            f"A task can collect at most {MAX_FIELDS} fields.",
            node_id=nid,
            field_="fields",
        )
    seen: set[str] = set()
    for i, f in enumerate(fields):
        if not isinstance(f, Mapping):
            out.error(
                "E_INVALID_SCHEMA", "Each field needs a name and a type.", node_id=nid, field_=f"fields.{i}"
            )
            continue
        name = f.get("name")
        if not isinstance(name, str) or not FIELD_NAME.match(name):
            out.error(
                "E_INVALID_SCHEMA",
                "Field names use lowercase letters, digits and underscores and start with a letter.",
                node_id=nid,
                field_=f"fields.{i}.name",
            )
        elif name in seen:
            out.error(
                "E_INVALID_SCHEMA", f"The field {name} appears twice.", node_id=nid, field_=f"fields.{i}.name"
            )
        else:
            seen.add(name)
        if f.get("type") not in TASK_FIELD_TYPES:
            out.error("E_INVALID_SCHEMA", "Choose a field type.", node_id=nid, field_=f"fields.{i}.type")
        elif f.get("type") == "enum" and not [
            v for v in f.get("enum_values") or [] if isinstance(v, str) and v
        ]:
            out.error(
                "E_INVALID_SCHEMA",
                "List the allowed values of this field.",
                node_id=nid,
                field_=f"fields.{i}.enum_values",
            )


def _check_condition(
    out: _Collector,
    n: Mapping[str, Any],
    cfg: Mapping[str, Any],
    kind: str,
    outs: Sequence[Mapping[str, Any]],
    by_trigger: Mapping[str, Sequence[Mapping[str, Any]]],
    set_variables: set[str],
) -> None:
    nid = str(n.get("id"))
    if cfg.get("kind", "classify") not in ("classify", "rule"):
        out.error("E_INVALID_FIELD", "Choose classify or rule.", node_id=nid, field_="kind")
    if not outs:
        out.error(
            "E_MISSING_OUTGOING", f"Connect {n.get('label') or 'this node'} to the next steps.", node_id=nid
        )
    if kind == "classify":
        categories = [c for c in cfg.get("categories") or [] if isinstance(c, Mapping)]
        if len(categories) > MAX_CATEGORIES:
            out.error(
                "E_LIMIT",
                f"A classify node can have at most {MAX_CATEGORIES} categories.",
                node_id=nid,
                field_="categories",
            )
        seen: set[str] = set()
        names: list[str] = []
        for i, c in enumerate(categories):
            name = _text(c.get("name"))
            if not CATEGORY_NAME.match(name):
                out.error(
                    "E_CATEGORY_NAME",
                    "Category names are 1 to 60 letters, digits, spaces, hyphens or underscores.",
                    node_id=nid,
                    field_=f"categories.{i}.name",
                )
            elif name.lower() in seen:
                out.error(
                    "E_CATEGORY_NAME",
                    f"{name} is already a category.",
                    node_id=nid,
                    field_=f"categories.{i}.name",
                )
            else:
                seen.add(name.lower())
                names.append(name)
        if len(categories) < 2:
            out.error(
                "E_CATEGORY_EDGES",
                "A classify node needs at least two categories.",
                node_id=nid,
                field_="categories",
            )
        cat_edges = by_trigger.get("category", [])
        for name in names:
            count = sum(1 for e in cat_edges if e.get("category") == name)
            if count != 1:
                out.error(
                    "E_CATEGORY_EDGES",
                    f"The category {name} needs exactly one connection."
                    if count == 0
                    else f"The category {name} has {count} connections; keep one.",
                    node_id=nid,
                )
        for e in cat_edges:
            if e.get("category") not in names:
                out.error(
                    "E_CATEGORY_EDGES",
                    "This connection's category no longer exists. Choose another or remove it.",
                    edge_id=str(e.get("id")),
                    field_="category",
                )
        return
    rules = by_trigger.get("rule", [])
    if not rules:
        out.error("E_EDGE_CARDINALITY", "Add at least one rule connection.", node_id=nid)
    if len(rules) > MAX_RULES:
        out.error("E_LIMIT", f"A rule node can have at most {MAX_RULES} rules.", node_id=nid)
    if len(by_trigger.get("else", [])) != 1:
        out.error("E_RULE_ELSE", "A rule node needs exactly one Otherwise connection.", node_id=nid)
    for e in rules:
        rule = e.get("rule")
        eid = str(e.get("id"))
        if not isinstance(rule, Mapping) or not _text(rule.get("variable")).strip():
            out.error(
                "E_REQUIRED_FIELD",
                "Choose the variable this rule checks.",
                edge_id=eid,
                field_="rule.variable",
            )
            continue
        if rule.get("operator") != "exists" and rule.get("value") in (None, ""):
            out.error(
                "E_REQUIRED_FIELD", "Enter the value to compare with.", edge_id=eid, field_="rule.value"
            )
        if rule.get("operator") == "matches":
            try:
                re.compile(str(rule.get("value") or ""))
            except re.error:
                out.error(
                    "E_INVALID_FIELD",
                    "This pattern is not a valid regular expression.",
                    edge_id=eid,
                    field_="rule.value",
                )
        variable = str(rule["variable"]).strip().strip("{} ")
        if variable not in set_variables:
            out.warn(
                "W_UNSET_VARIABLE",
                f"{variable} is never set by an earlier step and has no default.",
                node_id=nid,
            )


def _check_extract(out: _Collector, nid: str, cfg: Mapping[str, Any], seen_flow: dict[str, str]) -> None:
    fields = cfg.get("fields")
    if not isinstance(fields, list) or not fields:
        out.error("E_INVALID_SCHEMA", "Add at least one variable to extract.", node_id=nid, field_="fields")
        return
    if len(fields) > MAX_FIELDS:
        out.error(
            "E_INVALID_SCHEMA",
            f"An extract node can set at most {MAX_FIELDS} variables.",
            node_id=nid,
            field_="fields",
        )
    for i, f in enumerate(fields):
        if not isinstance(f, Mapping):
            out.error(
                "E_INVALID_SCHEMA",
                "Each variable needs a name and a type.",
                node_id=nid,
                field_=f"fields.{i}",
            )
            continue
        name = f.get("name")
        if not isinstance(name, str) or not FIELD_NAME.match(name):
            out.error(
                "E_INVALID_SCHEMA",
                "Variable names use lowercase letters, digits and underscores and start with a letter.",
                node_id=nid,
                field_=f"fields.{i}.name",
            )
        elif name in seen_flow:
            out.error(
                "E_INVALID_SCHEMA",
                f"Another step already sets {name}.",
                node_id=nid,
                field_=f"fields.{i}.name",
            )
        else:
            seen_flow[name] = nid
        if f.get("type") not in EXTRACT_FIELD_TYPES:
            out.error(
                "E_INVALID_SCHEMA",
                "Choose text, number or true/false.",
                node_id=nid,
                field_=f"fields.{i}.type",
            )


def _check_webhook(out: _Collector, nid: str, cfg: Mapping[str, Any], ctx: ValidationContext) -> list[str]:
    raw = cfg.get("request")
    request: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    url = _text(request.get("url")).strip()
    texts = [url, _text(request.get("execution_message"))]
    body = request.get("body_template")
    if isinstance(body, str):
        texts.append(body)
    for h in request.get("headers") or []:
        if isinstance(h, Mapping) and not h.get("secret"):
            texts.append(_text(h.get("value")))
    if not url:
        out.error("E_REQUIRED_FIELD", "Enter the URL this node calls.", node_id=nid, field_="request.url")
    else:
        scheme_ok = url.startswith("https://") or (ctx.allow_http_webhook and url.startswith("http://"))
        host = url.split("://", 1)[-1].split("/", 1)[0]
        if not scheme_ok or not host or " " in url:
            out.error(
                "E_INVALID_FIELD",
                "Enter a full https address, such as https://api.example.com/orders.",
                node_id=nid,
                field_="request.url",
            )
    try:
        HttpRequestSpec.model_validate({**request, "url": url or "https://x"})
    except ValidationError as exc:
        loc, msg = _pydantic_field(exc)
        out.error("E_INVALID_FIELD", msg, node_id=nid, field_=f"request.{loc}" if loc else "request")
    if isinstance(body, str) and body.strip() and not _json_ok(body):
        out.error(
            "E_INVALID_FIELD",
            "The body template is not valid JSON.",
            node_id=nid,
            field_="request.body_template",
        )
    mock = cfg.get("mock_response")
    if isinstance(mock, str) and mock.strip() and not _json_ok(mock):
        out.error(
            "E_INVALID_FIELD", "The canned response is not valid JSON.", node_id=nid, field_="mock_response"
        )
    return texts


def _check_transfer(out: _Collector, nid: str, cfg: Mapping[str, Any]) -> list[str]:
    raw = cfg.get("transfer")
    spec: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    texts = [_text(spec.get("hold_message")), _text(spec.get("routing_instructions"))]
    routing = spec.get("routing_type", "static")
    number = spec.get("number")
    if routing == "static":
        if not number:
            out.error(
                "E_REQUIRED_FIELD", "Enter the number to transfer to.", node_id=nid, field_="transfer.number"
            )
            return texts
        if not isinstance(number, str) or not E164.match(number):
            out.error(
                "E_INVALID_FIELD",
                "Use an international number such as +14155550100.",
                node_id=nid,
                field_="transfer.number",
            )
            return texts
    elif routing == "dynamic" and not _text(spec.get("routing_instructions")).strip():
        out.error(
            "E_REQUIRED_FIELD",
            "Describe how the agent picks the number.",
            node_id=nid,
            field_="transfer.routing_instructions",
        )
        return texts
    try:
        TransferSpec.model_validate(dict(spec))
    except ValidationError as exc:
        loc, msg = _pydantic_field(exc)
        out.error("E_INVALID_FIELD", msg, node_id=nid, field_=f"transfer.{loc}" if loc else "transfer")
    return texts


def counts(issues: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    errors = sum(1 for i in issues if i.get("severity") == "error")
    return errors, len(issues) - errors
