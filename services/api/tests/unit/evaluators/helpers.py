"""Context builders for evaluator unit tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.calls.transcript import FlowTransition, Message, ToolEvent
from app.evals import fakes
from app.evaluators.base import EvalContext, EvalTools, TurnLatency
from app.evaluators.judge import Judge
from app.llms.adapters.base import ChatMessage
from tests.fakes.fake_llm import FakeLlm

FLOW_NODES = {
    "start": {"type": "start", "label": "Start", "transitions": [{"target_node_id": "greet", "label": "go"}]},
    "greet": {
        "type": "conversation",
        "label": "Greeting",
        "instructions": "Greet and ask why they called.",
        "transitions": [
            {"target_node_id": "book", "label": "wants a booking"},
            {"target_node_id": "faq", "label": "has a question"},
            {"target_node_id": "end", "label": "nothing needed"},
        ],
    },
    "book": {
        "type": "conversation",
        "label": "Book slot",
        "transitions": [{"target_node_id": "end", "label": "done"}],
    },
    "faq": {
        "type": "conversation",
        "label": "Answer question",
        "transitions": [{"target_node_id": "greet", "label": "back"}],
    },
    "end": {"type": "end", "label": "Goodbye"},
    "xfer": {"type": "transfer", "label": "Front desk"},
}


def flow_config(**extra: Any) -> dict[str, Any]:
    return {
        "type": "flow",
        "flow": {
            "compiled": {"entry_node_id": "start", "persona_prompt": "Clinic scheduler", "nodes": FLOW_NODES}
        },
        **extra,
    }


def messages(*lines: tuple[str, str]) -> list[Message]:
    return [Message(i, role, text) for i, (role, text) in enumerate(lines)]  # type: ignore[arg-type]


def context(
    *,
    msgs: list[Message] | None = None,
    tools: list[ToolEvent] | None = None,
    path: list[str] | None = None,
    latencies: list[int] | None = None,
    config: Mapping[str, Any] | None = None,
    agent_type: str = "single_prompt",
    origin: str = "live",
) -> EvalContext:
    transitions = [FlowTransition(a, b) for a, b in zip(path or [], (path or [])[1:], strict=False)]
    return EvalContext(
        call_id="call_TEST",
        workspace_id="ws_TEST",
        agent_id="agt_TEST",
        agent_type=agent_type,  # type: ignore[arg-type]
        origin=origin,
        ended_at=datetime.now(UTC),
        disconnect_reason="user_hangup",
        config=config or {"prompt": "Book dental appointments.", "kb_ids": []},
        messages=msgs or [],
        tools=tools or [],
        transitions=transitions,
        latencies=[TurnLatency(i + 1, ms) for i, ms in enumerate(latencies or [])],
        run_id="evr_TEST",
    )


def offline_llm() -> FakeLlm:
    def responder(system: str, user: str, purpose: str | None) -> str:
        reply = fakes.judge_reply if purpose == "eval_judge" else fakes.analysis_reply
        return reply([ChatMessage("user", user)], system)

    return FakeLlm(responder=responder)


def tools(llm: FakeLlm | None = None, **kw: Any) -> EvalTools:
    return EvalTools(judge=Judge(llm or offline_llm()), judge_model="openai/gpt-5-mini", cutoff=0.5, **kw)


def judge_json(score: float, rationale: str = "Quoted line 1.", turns: list[int] | None = None) -> str:
    return json.dumps(
        {"verdict_hint": "fail", "score": score, "rationale": rationale, "evidence_turns": turns or [1]}
    )
