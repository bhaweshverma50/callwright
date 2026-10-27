"""``stuck_loop_detector``: the conversation kept returning to the same node (FR-043)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, ClassVar

from app.evaluators.base import (
    FLOW_ONLY,
    EvalContext,
    EvalOutcome,
    EvalTools,
    Evaluator,
    ItemResult,
    SettingsField,
)


class StuckLoopDetector(Evaluator):
    name = "stuck_loop_detector"
    display_name = "Stuck loops"
    description = "Flags nodes the conversation kept coming back to."
    agent_types = FLOW_ONLY
    enabled_by_default = True
    rules = "one item per visited node; fail when visits > max_visits_per_node"
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (
        SettingsField(
            "max_visits_per_node",
            "Maximum visits per node",
            "int",
            3,
            min=2,
            max=10,
            step=1,
            helper="Visiting a node more often than this fails the check. Default: {default}.",
        ),
    )

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        visited = ctx.visited_nodes()
        if not visited:
            return EvalOutcome.not_applicable("no flow path was recorded")
        limit = int(settings["max_visits_per_node"])
        counts = Counter(visited)
        items = []
        for node, visits in counts.items():
            label = ctx.node_label(node)
            if visits > limit:
                items.append(
                    ItemResult(
                        "fail",
                        float(visits),
                        f'"{label}" was visited {visits} times (limit {limit}).',
                        flow_node_id=node,
                        flow_node_label=label,
                    )
                )
            else:
                items.append(
                    ItemResult(
                        "pass",
                        float(visits),
                        f'"{label}" was visited {visits} time{"s" if visits != 1 else ""}.',
                        flow_node_id=node,
                        flow_node_label=label,
                    )
                )
        loops = [i for i in items if i.verdict == "fail"]
        rationale = (
            "; ".join(i.rationale for i in loops)
            if loops
            else f"No node was visited more than {limit} times."
        )
        return EvalOutcome(items, rationale=rationale)
