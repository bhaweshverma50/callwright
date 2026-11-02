"""Fix application (009 T029; research R4) and the drafting prompt (T030, ``drafting.py``).

``apply_fix(snapshot, kind, payload)`` is pure: it returns a new full agent configuration with
the fix applied and never touches its input. The same function builds the validation variant and
(through the validated snapshot) the applied version, so apply's hash check is a real guarantee.

* ``RedraftNeeded``: the payload's ``current_*`` value no longer matches the configuration (the
  prompt, node, tool or edge changed or was removed). Compared after trimming whitespace.
* ``InvalidFix``: the payload cannot apply to this kind of agent or element (an end node's
  instructions, a duplicate transition label, a tool the agent does not have).
* ``AdvisoryFix``: a ``kb_attach`` fix that only lists uncovered topics; it cannot run.

Flow agents: edits to the graph, the persona prompt, knowledge bases or node tools set
``flow.compiled`` to ``None`` so 008's variant resolution compiles the edited flow (004's
compiler) with the variant's settings. A tool description edit keeps the compiled flow and
patches the tool's spec in every compiled node, because the compiler reads tool specs from the
tool library rather than from the variant.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from typing import Any

CONVERSATIONAL = ("agent", "task")
RULES_HEADING = "## Rules"
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


class FixError(Exception):
    code = "invalid_fix"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RedraftNeeded(FixError):
    code = "redraft_needed"


class InvalidFix(FixError):
    code = "invalid_fix"


class AdvisoryFix(FixError):
    code = "advisory_fix"


def _same(a: Any, b: Any) -> bool:
    return str(a or "").strip() == str(b or "").strip()


def guardrail_text(text: str, rule: str) -> str:
    """``text`` with ``- rule`` added under a ``## Rules`` heading (created at the end when
    missing). Unchanged when the rule is already listed."""
    rule = " ".join(rule.split())
    bullet = f"- {rule}"
    lines = text.rstrip().splitlines()
    if any(line.strip() == bullet for line in lines):
        return text
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().lower() == RULES_HEADING.lower())
    except StopIteration:
        body = text.rstrip()
        return f"{body}\n\n{RULES_HEADING}\n{bullet}" if body else f"{RULES_HEADING}\n{bullet}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    insert = end
    while insert > start + 1 and not lines[insert - 1].strip():
        insert -= 1
    lines.insert(insert, bullet)
    return "\n".join(lines)


def _flow(config: dict[str, Any]) -> dict[str, Any]:
    flow = config.get("flow")
    if config.get("type") != "flow" or not isinstance(flow, dict) or not isinstance(flow.get("graph"), dict):
        raise InvalidFix("This fix needs a flow agent.")
    return flow


def _nodes(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in _flow(config)["graph"].get("nodes") or [] if isinstance(n, dict)]


def _edges(config: dict[str, Any]) -> list[dict[str, Any]]:
    graph = _flow(config)["graph"]
    edges = graph.get("edges")
    if not isinstance(edges, list):
        edges = graph["edges"] = []
    return [e for e in edges if isinstance(e, dict)]


def _node(config: dict[str, Any], node_id: str | None, *, conversational: bool = True) -> dict[str, Any]:
    found = next((n for n in _nodes(config) if n.get("id") == node_id), None)
    if found is None:
        raise RedraftNeeded("The flow node this fix changes no longer exists. Draft the fix again.")
    if conversational and found.get("type") not in CONVERSATIONAL:
        raise InvalidFix("Only agent and task nodes have instructions to change.")
    if not isinstance(found.get("config"), dict):
        found["config"] = {}
    return found


def _recompile(config: dict[str, Any]) -> None:
    if config.get("type") == "flow" and isinstance(config.get("flow"), dict):
        config["flow"]["compiled"] = None


def _prompt_edit(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    if not _same(config.get("prompt"), p.get("current_prompt")):
        raise RedraftNeeded("The agent prompt changed since this fix was drafted. Draft the fix again.")
    config["prompt"] = str(p["proposed_prompt"])
    _recompile(config)


def _node_prompt_edit(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    node = _node(config, p.get("node_id"))
    if not _same(node["config"].get("instructions"), p.get("current_instructions")):
        raise RedraftNeeded(
            "The node's instructions changed since this fix was drafted. Draft the fix again."
        )
    node["config"]["instructions"] = str(p["proposed_instructions"])
    _recompile(config)


def _add_guardrail(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    rule = str(p["rule_text"])
    placement = p.get("placement")
    if placement == "agent_prompt":
        config["prompt"] = guardrail_text(str(config.get("prompt") or ""), rule)
        _recompile(config)
        return
    if placement == "node":
        targets = [_node(config, p.get("node_id"))]
    elif placement == "all_agent_nodes":
        targets = [n for n in _nodes(config) if n.get("type") in CONVERSATIONAL]
        if not targets:
            raise InvalidFix("This flow has no agent nodes to add the rule to.")
    else:
        raise InvalidFix("Choose where the rule goes: the agent prompt, one node or every agent node.")
    for node in targets:
        if not isinstance(node.get("config"), dict):
            node["config"] = {}
        node["config"]["instructions"] = guardrail_text(str(node["config"].get("instructions") or ""), rule)
    _recompile(config)


def _tool_description_edit(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    tool_id = p.get("tool_id")
    specs = [t for t in config.get("tools") or [] if isinstance(t, dict) and t.get("tool_id") == tool_id]
    compiled = (config.get("flow") or {}).get("compiled") if isinstance(config.get("flow"), dict) else None
    node_specs: list[dict[str, Any]] = []
    if isinstance(compiled, dict):
        for node in (compiled.get("nodes") or {}).values():
            if isinstance(node, dict):
                node_specs += [
                    t for t in node.get("tools") or [] if isinstance(t, dict) and t.get("tool_id") == tool_id
                ]
    every = specs + node_specs
    if not every:
        raise RedraftNeeded(
            "The tool this fix changes is no longer attached to the agent. Draft the fix again."
        )
    if not all(_same(t.get("description"), p.get("current_description")) for t in every):
        raise RedraftNeeded("The tool's description changed since this fix was drafted. Draft the fix again.")
    for spec in every:
        spec["description"] = str(p["proposed_description"])


def _transition_condition_edit(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    edge = next((e for e in _edges(config) if e.get("id") == p.get("edge_id")), None)
    if edge is None:
        raise RedraftNeeded("The transition this fix changes no longer exists. Draft the fix again.")
    if edge.get("trigger") != "llm_condition":
        raise InvalidFix("Only transitions the agent decides on have a condition to change.")
    if not _same(edge.get("condition"), p.get("current_condition")):
        raise RedraftNeeded(
            "The transition's condition changed since this fix was drafted. Draft the fix again."
        )
    edge["condition"] = str(p["proposed_condition"])
    _recompile(config)


def edge_id_for(source: str, target: str, label: str) -> str:
    digest = int.from_bytes(hashlib.sha256(f"{source}|{target}|{label}".encode()).digest()[:8], "big")
    chars = []
    for _ in range(8):
        digest, rem = divmod(digest, 36)
        chars.append(_BASE36[rem])
    return "e_" + "".join(chars)


def _add_transition(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    source = _node(config, p.get("source_node_id"))
    target = next((n for n in _nodes(config) if n.get("id") == p.get("target_node_id")), None)
    if target is None:
        raise RedraftNeeded("The target node of this transition no longer exists. Draft the fix again.")
    if target.get("type") == "start":
        raise InvalidFix("A transition cannot lead back to the start node.")
    edges = _edges(config)
    label = str(p["edge_label"])
    if any(e.get("source") == source["id"] and e.get("label") == label for e in edges):
        raise InvalidFix(f"The node already has a transition named {label}. Choose another name.")
    order = max((int(e.get("sort_order") or 0) for e in edges), default=0) + 1
    edge_id = edge_id_for(str(source["id"]), str(target["id"]), label)
    if any(e.get("id") == edge_id for e in edges):
        raise InvalidFix("This transition already exists.")
    _flow(config)["graph"]["edges"].append(
        {
            "id": edge_id,
            "source": source["id"],
            "target": target["id"],
            "trigger": "llm_condition",
            "label": label,
            "condition": str(p["handoff_condition"]),
            "sort_order": order,
        }
    )
    _recompile(config)


def agent_tool_ids(config: Mapping[str, Any]) -> set[str]:
    """Tools this configuration knows: attached to the agent or to any node."""
    ids = {str(t) for t in config.get("tool_ids") or []}
    ids |= {str(t.get("tool_id")) for t in config.get("tools") or [] if isinstance(t, Mapping)}
    flow = config.get("flow")
    graph = flow.get("graph") if isinstance(flow, Mapping) else None
    for n in (graph or {}).get("nodes") or []:
        if isinstance(n, Mapping):
            ids |= {str(t) for t in (n.get("config") or {}).get("tool_ids") or []}
    return ids


def _node_tool_attachment(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    node = _node(config, p.get("node_id"))
    current = [str(t) for t in node["config"].get("tool_ids") or []]
    known = agent_tool_ids(config)
    attach = [str(t) for t in p.get("tools_to_attach") or []]
    detach = [str(t) for t in p.get("tools_to_detach") or []]
    unknown = [t for t in attach if t not in known]
    if unknown:
        raise InvalidFix(f"Attach the tool {unknown[0]} to the agent first, then draft the fix again.")
    missing = [t for t in detach if t not in current]
    if missing:
        raise RedraftNeeded(f"The node no longer uses {missing[0]}. Draft the fix again.")
    result = [t for t in current if t not in detach] + [t for t in attach if t not in current]
    node["config"]["tool_ids"] = list(dict.fromkeys(result))
    _recompile(config)


def _kb_attach(config: dict[str, Any], p: Mapping[str, Any]) -> None:
    attach = [str(k) for k in p.get("kb_ids_to_attach") or []]
    if not attach:
        raise AdvisoryFix(
            "No knowledge base covers these topics. Add the content to a knowledge base, then draft again."
        )
    config["kb_ids"] = list(dict.fromkeys([*(str(k) for k in config.get("kb_ids") or []), *attach]))
    # The knowledge block is resolved again from the new list (005's resolver).
    config.pop("knowledge", None)
    _recompile(config)


_APPLY: dict[str, Callable[[dict[str, Any], Mapping[str, Any]], None]] = {
    "prompt_edit": _prompt_edit,
    "node_prompt_edit": _node_prompt_edit,
    "add_guardrail": _add_guardrail,
    "tool_description_edit": _tool_description_edit,
    "transition_condition_edit": _transition_condition_edit,
    "add_transition": _add_transition,
    "node_tool_attachment": _node_tool_attachment,
    "kb_attach": _kb_attach,
}


def apply_fix(snapshot: Mapping[str, Any], kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """A new configuration with the fix applied (raises ``FixError`` subclasses)."""
    handler = _APPLY.get(kind)
    if handler is None:
        raise InvalidFix(f"Unknown fix kind {kind!r}.")
    config = copy.deepcopy(dict(snapshot))
    handler(config, payload)
    return config


def is_advisory(kind: str, payload: Mapping[str, Any]) -> bool:
    return kind == "kb_attach" and not (payload.get("kb_ids_to_attach") or [])
