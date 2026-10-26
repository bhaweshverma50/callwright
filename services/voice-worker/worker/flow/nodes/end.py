"""End node (T065, FR-018): the closing message, then hang-up with ``agent_hangup``; the
node's reason is stored on the move."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import registry
from worker.flow.registry import Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    spec = node.get("end") or {}
    reason = str(spec.get("reason") or "call_completed")
    run.state.variables["end_reason"] = reason
    await run.services.end(run.render(spec.get("message")).strip(), reason)
    return Stop(reason)


registry.register("end", handle)
