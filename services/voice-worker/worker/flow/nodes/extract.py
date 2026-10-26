"""Extract variable node (T062, FR-015): one silent structured pass over the conversation."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import registry
from worker.flow.registry import Move, Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    spec = node.get("extract") or {}
    schema = spec.get("json_schema") or {"type": "object", "properties": {}}
    started = time.perf_counter()
    try:
        values = await run.services.extract(run.render(spec.get("instructions")), schema)
    except Exception:
        values = {}
    model_ms = round((time.perf_counter() - started) * 1000)
    allowed = set((schema.get("properties") or {}).keys())
    found = {k: v for k, v in values.items() if k in allowed and v not in (None, "")}
    if not spec.get("next"):
        return Stop("flow_dead_end")
    return Move(
        target=str(spec["next"]),
        trigger="always",
        edge_id=spec.get("edge_id"),
        model_ms=model_ms,
        variables=found,
    )


registry.register("extract_variable", handle)
