"""Opening of a flow call (T058, FR-019, FR-042).

Who speaks first and the greeting come from the Start node. Say nodes right after Start are
spoken as part of the opening, so the existing pre-synthesised, uninterruptible greeting path
plays them at once. A caller-first flow with a short greeting plays it before listening; with
an empty greeting the agent waits. A generated greeting is written by the first conversational
node (the validator guarantees Start leads to one).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from worker.flow import registry
from worker.flow.compiled import StartSection
from worker.flow.registry import CONVERSATIONAL, Move, Outcome, Stop
from worker.flow.templating import render


@dataclass(frozen=True)
class Opening:
    start_speaker: Literal["agent", "user"]
    greeting: str | None
    moves: list[tuple[str, Move]] = field(default_factory=list)  # (from node, move) already taken
    next: tuple[str, Move] | None = None  # the move still to run after the opening

    @property
    def entry_node_id(self) -> str | None:
        """The conversational node the call starts in, when the opening lands on one."""
        return None if self.next is not None or not self.moves else self.moves[-1][1].target


def opening(compiled: Mapping[str, Any], variables: Mapping[str, Any]) -> Opening:
    nodes: Mapping[str, Mapping[str, Any]] = compiled.get("nodes") or {}
    start_id = str(compiled["entry_node_id"])
    start = StartSection.of(nodes[start_id]["start"])
    speaker = start.start_speaker
    parts: list[str] = []
    text = render(start.greeting, variables)[0].strip()
    if text and (speaker == "user" or start.greeting_type == "static"):
        parts.append(text)
    moves: list[tuple[str, Move]] = []
    if not start.next:
        return Opening(speaker, None)
    move = Move(target=start.next, trigger="always", edge_id=start.edge_id)
    source = start_id
    while True:
        node = nodes.get(move.target) or {}
        if node.get("type") == "say" and (node.get("say") or {}).get("next"):
            say = node["say"]
            spoken = render(say.get("message"), variables)[0].strip()
            if spoken:
                parts.append(spoken)
            moves.append((source, move))
            source = move.target
            move = Move(target=str(say["next"]), trigger="always", edge_id=say.get("edge_id"))
            continue
        break
    greeting = " ".join(parts) or None
    first_speaker: Literal["agent", "user"] = "agent" if greeting else speaker
    if speaker == "agent" and start.greeting_type == "generated":
        first_speaker = "agent"
    node_type = (nodes.get(move.target) or {}).get("type")
    if node_type in CONVERSATIONAL:
        moves.append((source, move))
        return Opening(first_speaker, greeting, moves, None)
    return Opening(first_speaker, greeting, moves, (source, move))


async def handle(run: Any, node_id: str, node: Mapping[str, Any]) -> Outcome:
    """Start as a plain node (a move back into Start): continue to its first step."""
    start = StartSection.of(node["start"])
    if not start.next:
        return Stop("flow_dead_end")
    return Move(target=start.next, trigger="always", edge_id=start.edge_id)


registry.register("start", handle)
