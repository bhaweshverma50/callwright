"""``node_dead_end``: per visited node, the conversation moved on or ended there mid-flow (FR-043)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.evaluators.base import FLOW_ONLY, EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult
from app.evaluators.builtins.flow_completion import FINAL_NODE_TYPES, last_node


class NodeDeadEnd(Evaluator):
    name = "node_dead_end"
    display_name = "Node dead ends"
    description = "Flags the node where a call ended mid-flow, without an end or transfer."
    agent_types = FLOW_ONLY
    enabled_by_default = True
    rules = "one item per visited node; fail on the final node when it is not end or transfer"

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        visited = ctx.visited_nodes()
        final = last_node(ctx)
        if not visited and final:
            visited = [final]
        if not visited:
            return EvalOutcome.not_applicable("no flow path was recorded")
        items: list[ItemResult] = []
        for node in dict.fromkeys(visited):
            label = ctx.node_label(node)
            kind = ctx.node_type(node)
            if node != final:
                items.append(
                    ItemResult(
                        "pass",
                        1.0,
                        f'The conversation moved on from "{label}".',
                        flow_node_id=node,
                        flow_node_label=label,
                    )
                )
            elif kind in FINAL_NODE_TYPES:
                items.append(
                    ItemResult(
                        "pass",
                        1.0,
                        f'The call ended on the {kind} node "{label}".',
                        flow_node_id=node,
                        flow_node_label=label,
                    )
                )
            else:
                items.append(
                    ItemResult(
                        "fail",
                        0.0,
                        f'The call ended on "{label}" mid-flow, without an end or transfer.',
                        flow_node_id=node,
                        flow_node_label=label,
                    )
                )
        failed = [i for i in items if i.verdict == "fail"]
        rationale = failed[0].rationale if failed else f"No dead end across {len(items)} visited nodes."
        return EvalOutcome(items, rationale=rationale)
