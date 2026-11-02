"""Fix kinds allowed per agent type and issue attribution (009 T028; spec FR-008).

The recommended kind comes first in every list.
"""

from __future__ import annotations

SINGLE_PROMPT = ["prompt_edit", "add_guardrail", "tool_description_edit", "kb_attach"]
FLOW_NODE = [
    "node_prompt_edit",
    "add_guardrail",
    "transition_condition_edit",
    "add_transition",
    "node_tool_attachment",
    "tool_description_edit",
    "kb_attach",
]
FLOW_OTHER = ["add_guardrail", "tool_description_edit", "kb_attach"]


def allowed_kinds(agent_type: str, flow_node_id: str | None) -> list[str]:
    if agent_type != "flow":
        return list(SINGLE_PROMPT)
    return list(FLOW_NODE if flow_node_id else FLOW_OTHER)


def recommended_kind(agent_type: str, flow_node_id: str | None) -> str:
    return allowed_kinds(agent_type, flow_node_id)[0]


def is_allowed(agent_type: str, flow_node_id: str | None, kind: str) -> bool:
    return kind in allowed_kinds(agent_type, flow_node_id)
