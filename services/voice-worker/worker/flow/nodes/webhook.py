"""Webhook node (T063, FR-016) over 005's HTTP executor.

Mapped response values become flow variables. A failure follows the failure connection, or the
success path with the failure noted on the move when there is none (US3 scenario 6).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import registry
from worker.flow.registry import Move, Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    spec = node.get("webhook") or {}
    try:
        result = await run.services.webhook(
            node_id, spec.get("request") or {}, spec.get("mock_response"), run.state.variables
        )
    except Exception as exc:
        from worker.flow.executor import WebhookResult

        result = WebhookResult(ok=False, detail=type(exc).__name__)
    if result.ok and spec.get("success_target"):
        return Move(
            target=str(spec["success_target"]),
            trigger="success",
            edge_id=spec.get("success_edge_id"),
            variables=dict(result.mapped),
        )
    if not result.ok and spec.get("failure_target"):
        return Move(
            target=str(spec["failure_target"]),
            trigger="failure",
            edge_id=spec.get("failure_edge_id"),
            note=result.detail,
        )
    if spec.get("success_target"):
        return Move(
            target=str(spec["success_target"]),
            trigger="success",
            edge_id=spec.get("success_edge_id"),
            note=f"webhook failed: {result.detail or 'error'}",
        )
    return Stop("flow_dead_end")


registry.register("webhook", handle)
