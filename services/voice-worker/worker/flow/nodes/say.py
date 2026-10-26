"""Say node (T061, FR-014): a fixed line without the model; interruptible or not."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from worker.flow import registry
from worker.flow.registry import Move, Outcome, Stop

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun


async def handle(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Outcome:
    say = node.get("say") or {}
    text = run.render(say.get("message")).strip()
    if text:
        await run.services.say(text, allow_interruptions=bool(say.get("allow_interruptions", True)))
    if not say.get("next"):
        return Stop("flow_dead_end")
    return Move(target=str(say["next"]), trigger="always", edge_id=say.get("edge_id"))


registry.register("say", handle)
