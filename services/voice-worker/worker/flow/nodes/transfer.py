"""Transfer node (T064, FR-017) over 005's transfer executor.

A successful transfer ends the agent's part of the call. When it fails (or the call is a web
call, where transfers are not possible) the failure connection is followed; without one the
agent says the transfer is unavailable and the call goes back to the last conversational node.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import registry
from worker.flow.registry import CONVERSATIONAL, Move, Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun

UNAVAILABLE = "I'm not able to transfer you right now, but I can keep helping you here."


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    spec = node.get("transfer") or {}
    try:
        transferred = await run.services.transfer(node_id, spec.get("transfer") or {})
    except Exception:
        transferred = False
    if transferred:
        return Stop("call_transfer")
    if spec.get("failure_target"):
        return Move(
            target=str(spec["failure_target"]),
            trigger="failure",
            edge_id=spec.get("failure_edge_id"),
        )
    back = next(
        (n for n in reversed(run.state.visited) if run.node(n).get("type") in CONVERSATIONAL), None
    )
    await run.services.say(UNAVAILABLE)
    if back is None:
        await run.services.hang_up("error", diagnostic="flow_transfer_failed")
        return Stop("error")
    return Move(target=back, trigger="fallback", note="transfer unavailable")


registry.register("transfer", handle)
