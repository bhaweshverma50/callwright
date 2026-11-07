"""Condition node (T060, FR-013, research R11).

``classify``: one constrained model call picks a category (the runtime caps it at 1500 ms);
on timeout or an answer outside the list the first category is followed with trigger
``fallback``. ``rule``: the safe evaluator checks the rules in order, else ``else``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import registry, rules
from worker.flow.registry import Move, Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun

log = logging.getLogger("callwright.flow")


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    cond = node.get("condition") or {}
    if cond.get("kind") == "rule":
        matched = rules.first_match(cond.get("rules") or [], run.state.variables)
        if matched is not None:
            return Move(
                target=str(matched["target"]),
                trigger="rule",
                edge_id=matched.get("edge_id"),
                label=matched.get("label"),
            )
        if cond.get("else_target"):
            return Move(
                target=str(cond["else_target"]),
                trigger="else",
                edge_id=cond.get("else_edge_id"),
                label="Otherwise",
            )
        return Stop("flow_dead_end")
    categories = [c for c in cond.get("categories") or [] if c.get("target")]
    if not categories:
        return Stop("flow_dead_end")
    started = time.perf_counter()
    try:
        choice = await run.services.classify(run.render(cond.get("instructions")), categories)
    except Exception:  # a failed classify must not end the call
        log.exception("flow condition node %s failed on %s", node_id, run.call_id)
        choice = None
    model_ms = round((time.perf_counter() - started) * 1000)
    chosen = next(
        (
            c
            for c in categories
            if choice is not None and str(c["name"]).lower() == str(choice).lower()
        ),
        None,
    )
    if chosen is None:
        first = categories[0]
        return Move(
            target=str(first["target"]),
            trigger="fallback",
            edge_id=first.get("edge_id"),
            label=first.get("name"),
            model_ms=model_ms,
        )
    return Move(
        target=str(chosen["target"]),
        trigger="category",
        edge_id=chosen.get("edge_id"),
        label=chosen.get("name"),
        model_ms=model_ms,
    )


registry.register("condition", handle)
