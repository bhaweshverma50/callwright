"""End node (T065, FR-018): the closing line, then hang-up with ``agent_hangup``; the node's
reason is stored on the move.

An End node whose message is empty or the stock default (``STOCK_END_MESSAGE``, what new flows
used to get) does not speak a canned line over whatever the caller just asked: the agent says a
short goodbye that fits the call, written by the call's model (flow/runtime.py, bounded wait,
the stock line when the model fails). A message the builder wrote is spoken word for word.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import llm_ops, registry
from worker.flow.registry import Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun

# The default End message of flows built before the goodbye was generated (API starter, web
# flow model); treated like an empty message.
STOCK_END_MESSAGE = llm_ops.STOCK_GOODBYE


def generates(node: Mapping[str, Any]) -> bool:
    """True when the End node has no line of its own and the agent writes the goodbye."""
    message = str((node.get("end") or {}).get("message") or "").strip()
    return not message or message == STOCK_END_MESSAGE


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    spec = node.get("end") or {}
    reason = str(spec.get("reason") or "call_completed")
    run.state.variables["end_reason"] = reason
    if generates(node):
        await run.services.end(STOCK_END_MESSAGE, reason, generate=True)
    else:
        await run.services.end(run.render(spec.get("message")).strip(), reason)
    return Stop(reason)


registry.register("end", handle)
