"""Handler registry, unknown node types and the 200-move guard (004 T049)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest

from tests.flow_support import compiled_config
from worker.flow import (
    nodes,  # noqa: F401  (registers the handlers)
    registry,
)
from worker.flow.events import FlowEvents
from worker.flow.executor import FlowRun, WebhookResult
from worker.flow.registry import Move, UnknownNodeType


class Services:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.hung_up: tuple[str, str | None] | None = None

    async def say(self, text: str, *, allow_interruptions: bool = True) -> None:
        self.said.append(text)

    async def classify(self, instructions: str, categories: list[Mapping[str, Any]]) -> str | None:
        return None

    async def extract(self, instructions: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        return {}

    async def webhook(
        self,
        node_id: str,
        request: Mapping[str, Any],
        mock: str | None,
        variables: Mapping[str, Any],
    ) -> WebhookResult:
        return WebhookResult(ok=True)

    async def transfer(self, node_id: str, spec: Mapping[str, Any]) -> bool:
        return False

    async def end(self, message: str, reason: str) -> None:
        self.said.append(message)
        self.hung_up = ("agent_hangup", None)

    async def hang_up(self, reason: str, diagnostic: str | None = None) -> None:
        self.hung_up = (reason, diagnostic)


def compiled(name: str) -> dict[str, Any]:
    return copy.deepcopy(compiled_config(name)["flow"]["compiled"])


def test_every_node_type_has_a_handler_or_is_conversational() -> None:
    assert registry.registered() >= {
        "start",
        "say",
        "condition",
        "extract_variable",
        "webhook",
        "transfer",
        "end",
    }
    with pytest.raises(ValueError):
        registry.register("agent", lambda *_: None)  # type: ignore[arg-type]


def test_unknown_node_type_is_refused_before_the_call() -> None:
    flow = compiled("triage_support")
    flow["nodes"]["n_route000"]["type"] = "teleport"
    with pytest.raises(UnknownNodeType):
        FlowRun(flow, Services(), FlowEvents(None))


async def test_custom_handler_registration() -> None:
    async def hop(run: FlowRun, node_id: str, node: Mapping[str, Any]) -> Move:
        return Move(target="n_end00000", trigger="always")

    registry.register("hop", hop)
    try:
        flow = compiled("triage_support")
        flow["nodes"]["n_route000"]["type"] = "hop"
        services = Services()
        run = FlowRun(flow, services, FlowEvents(None))
        landing = await run.advance(
            "n_triage00", Move(target="n_route000", trigger="llm_condition")
        )
        assert landing.ended and run.state.visited[-1] == "n_end00000"
    finally:
        registry._handlers.pop("hop", None)


async def test_transition_guard_ends_the_call() -> None:
    services = Services()
    run = FlowRun(compiled("loop_guard"), services, FlowEvents(None))
    landing = await run.advance("n_triage00", Move(target="n_extrA000", trigger="llm_condition"))
    assert landing.ended and run.state.transition_count == 200
    assert services.hung_up == ("error", "flow_transition_limit")


async def test_first_transition_of_a_turn_wins() -> None:
    run = FlowRun(compiled("triage_support"), Services(), FlowEvents(None))
    assert run.claim_turn(1) is True
    assert run.claim_turn(1) is False
    assert run.claim_turn(2) is True
