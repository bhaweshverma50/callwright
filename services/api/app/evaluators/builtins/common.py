"""Shared helpers for the built-in judges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.calls.transcript import Message, ToolEvent
from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, ItemResult
from app.evaluators.judge import JudgeResult
from app.flows.compiled import compiled_view


def judge_model(settings: Mapping[str, Any], tools: EvalTools) -> str:
    return str(settings.get("judge_model") or tools.judge_model)


def agent_goal(ctx: EvalContext, limit: int = 3000) -> str:
    """The agent's instructions from the version the call ran (prompt, or the flow persona)."""
    prompt = ctx.config.get("prompt") or compiled_view(ctx.config).persona_prompt
    text = str(prompt or "(no written instructions)").strip()
    return text[:limit]


def outcome_from(result: JudgeResult, model: str) -> EvalOutcome:
    j = result.judgement
    item = ItemResult(
        j.verdict,
        j.score,
        j.rationale,
        evidence={"turn_indices": j.evidence_turns, "quote": j.quote},
    )
    return EvalOutcome(
        [item],
        rationale=j.rationale,
        judge_model=model,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        raw_cost_usd=result.usage.raw_cost_usd,
    )


async def judge_call(
    ctx: EvalContext,
    settings: Mapping[str, Any],
    tools: EvalTools,
    task: str,
    *,
    messages: Sequence[Message] | None = None,
    tool_events: Sequence[ToolEvent] | None = None,
) -> EvalOutcome:
    model = judge_model(settings, tools)
    result = await tools.judge.score_call(
        model,
        task=task,
        messages=ctx.messages if messages is None else messages,
        tools=ctx.tools if tool_events is None else tool_events,
    )
    return outcome_from(result, model)
