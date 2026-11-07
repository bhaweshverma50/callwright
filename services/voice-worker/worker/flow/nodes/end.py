"""End node (T065, FR-018): the closing line, then hang-up with ``agent_hangup``; the node's
reason is stored on the move.

An End node whose message is empty or the stock default (``STOCK_GOODBYE``, what new flows
used to get) does not speak a canned line over whatever the caller just asked: the agent says a
short goodbye that fits the call, written by the call's model (flow/runtime.py, bounded wait,
the stock line when the model fails). A message the builder wrote is spoken word for word.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from callwright_contract.values import STOCK_GOODBYE

from worker.flow import registry
from worker.flow.compiled import EndSection
from worker.flow.registry import Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun


def generates(node: Mapping[str, Any]) -> bool:
    """True when the End node has no line of its own and the agent writes the goodbye."""
    message = EndSection.of(node.get("end")).message.strip()
    return not message or message == STOCK_GOODBYE


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    end = EndSection.of(node.get("end"))
    run.state.variables["end_reason"] = end.reason
    if generates(node):
        await run.services.end(STOCK_GOODBYE, end.reason, generate=True)
    else:
        await run.services.end(run.render(end.message).strip(), end.reason)
    return Stop(end.reason)


registry.register("end", handle)
