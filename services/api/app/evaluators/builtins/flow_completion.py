"""``flow_completion``: the call reached an end or transfer node (FR-043)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.evaluators.base import FLOW_ONLY, EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult

FINAL_NODE_TYPES = frozenset({"end", "transfer"})


def last_node(ctx: EvalContext) -> str | None:
    if ctx.transitions:
        return ctx.transitions[-1].to_node_id
    flow = ctx.config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    entry = compiled.get("entry_node_id") if isinstance(compiled, Mapping) else None
    return str(entry) if entry else None


class FlowCompletion(Evaluator):
    name = "flow_completion"
    display_name = "Flow completion"
    description = "Passes when the conversation reached an end or transfer node of the flow."
    agent_types = FLOW_ONLY
    enabled_by_default = True
    rules = "pass when the last visited node is an end or transfer node"

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        node = last_node(ctx)
        if node is None:
            return EvalOutcome.not_applicable("no flow path was recorded")
        label = ctx.node_label(node)
        kind = ctx.node_type(node)
        if kind in FINAL_NODE_TYPES:
            item = ItemResult(
                "pass",
                1.0,
                f'The call finished on the {kind} node "{label}".',
                flow_node_id=node,
                flow_node_label=label,
            )
        else:
            item = ItemResult(
                "fail",
                0.0,
                (
                    f'The call stopped on "{label}" ({kind or "unknown"} node) without reaching an end or '
                    "transfer node."
                ),
                flow_node_id=node,
                flow_node_label=label,
            )
        return EvalOutcome([item], rationale=item.rationale)
