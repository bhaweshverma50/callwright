"""What the simulated callers (replay, persona) need from a text session, and how a run ends."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from callwright_contract.textsim import SimulationEndReason

# Disconnect reason on the simulated call's final ``ended`` status for each end reason.
DISCONNECT_REASON: dict[str, str] = {
    "caller_turns_exhausted": "user_hangup",
    "caller_hung_up": "user_hangup",
    "turn_limit_reached": "user_hangup",
    "agent_hangup": "agent_hangup",
    "call_transfer": "call_transfer",
    "error": "error",
}


@dataclass(frozen=True)
class AgentTurn:
    """What the agent said in one turn: turn 0 is the opening, turn k the reply to caller turn
    k (tool calls and flow moves included). ``ended`` is the disconnect reason when the call
    ended during the turn."""

    index: int
    texts: list[str] = field(default_factory=list)
    ended: str | None = None


class Conversation(Protocol):
    @property
    def disconnect_reason(self) -> str | None: ...

    @property
    def turn_index(self) -> int: ...

    @property
    def visited_nodes(self) -> Sequence[str]:
        """Flow agents: node ids in the order they were entered (empty otherwise)."""
        ...

    async def start(self) -> AgentTurn:
        """Start the session and play the agent's opening when the agent speaks first."""
        ...

    async def send(self, text: str) -> AgentTurn:
        """One caller turn; returns once the agent's reply (and any handoffs) settled."""
        ...


@dataclass(frozen=True)
class Outcome:
    end_reason: SimulationEndReason
    diverged_at_turn: int | None = None
    caller_turns: int = 0
    hang_up_reason: str | None = None


def agent_end_reason(disconnect_reason: str | None) -> SimulationEndReason | None:
    """The end reason when the agent side ended the call (None while it is still running)."""
    if disconnect_reason is None:
        return None
    if disconnect_reason == "agent_hangup":
        return "agent_hangup"
    if disconnect_reason == "call_transfer":
        return "call_transfer"
    return "error"
