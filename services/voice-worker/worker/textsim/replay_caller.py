"""Replay caller (008 T055, research R5).

The caller turns are the base call's user messages in order. The API merges interrupted
fragments when it builds them; :func:`normalize_turns` does it again defensively (items may be
``{"text", "interrupted"}`` objects, where an interrupted fragment joins the next one) and drops
empty turns.

The agent's opening (when the target agent speaks first) plays before caller turn 1; each next
caller turn is sent once the agent's reply, tool calls and flow moves included, has settled.
The run stops when the caller turns run out (``caller_turns_exhausted``), the agent ends or
transfers the call, or after :data:`MAX_AGENT_TURNS` replies (``turn_limit_reached``).

Divergence is the first agent turn index (0 is the opening, k the reply to caller turn k) at
which the agent ended or transferred while caller turns remained, or, for flow agents, the
visited node sequence stopped matching the base call's node path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from callwright_contract.values import SimulationEndReason

from worker.textsim.conversation import Conversation, Outcome, agent_end_reason

MAX_AGENT_TURNS = 50


def normalize_turns(raw: Sequence[Any]) -> list[str]:
    out: list[str] = []
    pending = ""
    for item in raw:
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("content") or "")
            interrupted = bool(item.get("interrupted"))
        else:
            text, interrupted = str(item or ""), False
        text = " ".join(text.split())
        if text:
            pending = f"{pending} {text}" if pending else text
        if interrupted or not pending:
            continue
        out.append(pending)
        pending = ""
    if pending:
        out.append(pending)
    return out


def path_diverged(visited: Sequence[str], original: Sequence[str]) -> bool:
    """True once the visited nodes stop being a prefix of the original path."""
    if any(a != b for a, b in zip(visited, original, strict=False)):
        return True
    return len(visited) > len(original)


class ReplayCaller:
    def __init__(
        self,
        caller_turns: Sequence[Any],
        original_node_path: Sequence[str] = (),
        *,
        max_agent_turns: int = MAX_AGENT_TURNS,
    ) -> None:
        self.turns = normalize_turns(caller_turns)
        self.original = list(original_node_path)
        self.max_agent_turns = max_agent_turns
        self.diverged_at: int | None = None

    def _check_path(self, conversation: Conversation, turn_index: int) -> None:
        if self.diverged_at is not None or not self.original:
            return
        visited = list(conversation.visited_nodes)
        if visited and path_diverged(visited, self.original):
            self.diverged_at = turn_index

    async def drive(self, conversation: Conversation) -> Outcome:
        opening = await conversation.start()
        self._check_path(conversation, opening.index)
        sent = 0
        limit_hit = False
        for text in self.turns:
            if conversation.disconnect_reason is not None:
                break
            if sent >= self.max_agent_turns:
                limit_hit = True
                break
            turn = await conversation.send(text)
            sent += 1
            self._check_path(conversation, turn.index)
        end: SimulationEndReason
        ended = agent_end_reason(conversation.disconnect_reason)
        if ended is not None:
            end = ended
            if sent < len(self.turns) and self.diverged_at is None:
                self.diverged_at = conversation.turn_index
        elif limit_hit:
            end = "turn_limit_reached"
        else:
            end = "caller_turns_exhausted"
        return Outcome(end_reason=end, diverged_at_turn=self.diverged_at, caller_turns=sent)
