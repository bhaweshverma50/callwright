"""Flow state machine (T057; data-model section 8, research R10).

:class:`FlowRun` owns the per-call run state and moves the call through non-conversational
nodes (say, condition, extract, webhook, transfer, end) with the handlers in the registry until
it lands on a conversational node (agent or task) or the call ends. Everything that touches the
call (speech, models, HTTP, transfers, hang-up) goes through :class:`FlowServices`, so the
executor runs unchanged in the live worker, the text-mode tests and the benchmarks.

A guard of 200 moves per call ends the call with disconnect reason ``error`` to stop runaway
loops between non-conversational nodes. Only the first transition of a turn is honoured
(``claim_turn``); the model is told a second one was ignored.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from worker import telemetry
from worker.flow import registry
from worker.flow.events import FlowEvents
from worker.flow.registry import CONVERSATIONAL, Move, Stop
from worker.flow.templating import render

MAX_TRANSITIONS = 200


@dataclass(frozen=True)
class WebhookResult:
    ok: bool
    mapped: Mapping[str, Any] = field(default_factory=dict)
    detail: str | None = None


class FlowServices(Protocol):
    async def say(self, text: str, *, allow_interruptions: bool = True) -> None: ...

    async def classify(
        self, instructions: str, categories: list[Mapping[str, Any]]
    ) -> str | None: ...

    async def extract(self, instructions: str, schema: Mapping[str, Any]) -> dict[str, Any]: ...

    async def webhook(
        self,
        node_id: str,
        request: Mapping[str, Any],
        mock_response: str | None,
        variables: Mapping[str, Any],
    ) -> WebhookResult: ...

    async def transfer(self, node_id: str, spec: Mapping[str, Any]) -> bool: ...

    async def end(self, message: str, reason: str) -> None: ...

    async def hang_up(self, reason: str, diagnostic: str | None = None) -> None: ...


@dataclass
class FlowRunState:
    current_node_id: str
    visited: list[str] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    task_rounds: dict[str, int] = field(default_factory=dict)
    summary: str | None = None
    transition_count: int = 0
    ended: bool = False
    turn_moved: int | None = None  # turn index of the last honoured transition


@dataclass(frozen=True)
class Landing:
    """Where a move chain stopped: a conversational node, or the end of the call."""

    node_id: str | None
    ended: bool = False


class FlowRun:
    def __init__(
        self,
        compiled: Mapping[str, Any],
        services: FlowServices,
        events: FlowEvents,
        variables: Mapping[str, Any] | None = None,
        *,
        max_transitions: int = MAX_TRANSITIONS,
        clock: Callable[[], float] = time.perf_counter,
        call_id: str | None = None,
    ) -> None:
        self.compiled = compiled
        self.nodes: Mapping[str, Mapping[str, Any]] = compiled.get("nodes") or {}
        registry.check_types(self.nodes)
        self.services = services
        self.events = events
        self.state = FlowRunState(
            current_node_id=str(compiled["entry_node_id"]), variables=dict(variables or {})
        )
        self.state.visited.append(self.state.current_node_id)
        self.max_transitions = max_transitions
        self.clock = clock
        self.call_id = call_id
        self.engine_ms: list[int] = []
        self.on_engine: Callable[[int], None] | None = None

    # helpers ---------------------------------------------------------------------------

    def node(self, node_id: str) -> Mapping[str, Any]:
        return self.nodes[node_id]

    def render(self, text: str | None) -> str:
        return render(text, self.state.variables)[0]

    def claim_turn(self, turn_index: int) -> bool:
        """True for the first transition of ``turn_index``; later ones are ignored."""
        if self.state.turn_moved == turn_index:
            return False
        self.state.turn_moved = turn_index
        return True

    # moves -----------------------------------------------------------------------------

    def record(self, from_id: str | None, move: Move, started: float) -> None:
        engine_ms = round((self.clock() - started) * 1000)
        self.engine_ms.append(engine_ms)
        if self.on_engine is not None:
            self.on_engine(engine_ms)
        if move.variables:
            self.state.variables.update(move.variables)
        self.events.move(
            self.nodes.get(from_id or "") if from_id else None,
            from_id,
            self.node(move.target),
            move.target,
            trigger=move.trigger,
            edge_id=move.edge_id,
            edge_label=move.label,
            function_name=move.function_name,
            engine_ms=engine_ms,
            model_ms=move.model_ms,
            variables=move.variables,
            note=move.note,
        )
        self.state.current_node_id = move.target
        self.state.visited.append(move.target)

    async def advance(self, from_id: str | None, move: Move) -> Landing:
        """Follow ``move`` and every non-conversational node after it."""
        source = from_id
        current: Move | None = move
        while current is not None:
            started = self.clock()
            if self.state.ended:
                return Landing(None, ended=True)
            if self.state.transition_count >= self.max_transitions:
                self.state.ended = True
                await self.services.hang_up("error", diagnostic="flow_transition_limit")
                return Landing(None, ended=True)
            if current.target not in self.nodes:
                self.state.ended = True
                await self.services.hang_up(
                    "error", diagnostic=f"flow_unknown_node:{current.target}"
                )
                return Landing(None, ended=True)
            self.state.transition_count += 1
            attrs = {
                "call_id": self.call_id or "",
                "node_id": current.target,
                "trigger": current.trigger,
            }
            with telemetry.span("flow.transition", attrs):
                self.record(source, current, started)
            target = self.node(current.target)
            node_type = str(target.get("type"))
            if node_type in CONVERSATIONAL:
                return Landing(current.target)
            with telemetry.span(
                "flow.node",
                {"call_id": self.call_id or "", "node_id": current.target, "node_type": node_type},
            ):
                outcome = await registry.handler_for(node_type)(self, current.target, target)
            if isinstance(outcome, Stop):
                self.state.ended = True
                return Landing(None, ended=True)
            source, current = current.target, outcome
        return Landing(None, ended=True)  # pragma: no cover

    def transition_move(self, node_id: str, function_name: str) -> Move | None:
        node = self.node(node_id)
        for t in node.get("transitions") or []:
            if t.get("function_name") == function_name:
                return Move(
                    target=str(t["target_node_id"]),
                    trigger="llm_condition",
                    edge_id=t.get("edge_id"),
                    label=t.get("label"),
                    function_name=function_name,
                )
        return None
