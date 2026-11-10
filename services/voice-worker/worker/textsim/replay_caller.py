"""Replay caller (008 T055, research R5).

The caller turns are the base call's user messages in order, interrupted fragments already
merged by the API; :func:`normalize_turns` drops empty ones.

The agent's opening (when the target agent speaks first) plays before caller turn 1; each next
caller turn is sent once the agent's reply, tool calls and flow moves included, has settled.
The run stops when the caller turns run out (``caller_turns_exhausted``), the agent ends or
transfers the call, or after the contract's ``MAX_CALLER_TURNS`` replies (``turn_limit_reached``).

Divergence is the first agent turn index (0 is the opening, k the reply to caller turn k) at
which the agent ended or transferred while caller turns remained, or, for flow agents, the
visited node sequence stopped matching the base call's node path.
"""

from __future__ import annotations

from collections.abc import Sequence

from callwright_contract.textsim import MAX_CALLER_TURNS, SimulationEndReason

from worker.textsim.conversation import Conversation, Outcome, agent_end_reason


def normalize_turns(raw: Sequence[str]) -> list[str]:
    """The turns with their spacing collapsed, empty ones dropped."""
    return [text for text in (" ".join(t.split()) for t in raw) if text]


def path_diverged(visited: Sequence[str], original: Sequence[str]) -> bool:
    """True once the visited nodes stop being a prefix of the original path."""
    if any(a != b for a, b in zip(visited, original, strict=False)):
        return True
    return len(visited) > len(original)


class ReplayCaller:
    def __init__(
        self,
        caller_turns: Sequence[str],
        original_node_path: Sequence[str] = (),
        *,
        max_agent_turns: int = MAX_CALLER_TURNS,
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
