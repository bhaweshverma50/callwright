"""``process_reward``: each agent turn scored -1 regression, 0 neutral, +1 progress (judge)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.evals.scoring import process_reward_verdict
from app.evaluators.base import (
    EvalContext,
    EvalOutcome,
    EvalTools,
    Evaluator,
    ItemResult,
    SettingsField,
    judge_model_field,
)
from app.evaluators.builtins.common import agent_goal, judge_model

TASK = (
    "Score every AGENT line listed under SCORE for how it moves the call toward the goal in the "
    "agent's instructions: 1 progress (gathers what is needed, answers, completes a step), 0 "
    "neutral (small talk, repeats, holds), -1 regression (wrong information, ignores the caller, "
    "loses progress, refuses without a way forward).\n\nAGENT INSTRUCTIONS:\n{goal}"
)


class ProcessReward(Evaluator):
    name = "process_reward"
    display_name = "Per-turn progress"
    description = "Scores each agent turn as progress, neutral or a step backwards toward the call's goal."
    scope = "turn"
    cost_class = "llm_judge"
    output_kind = "process_reward"
    score_range = (-1.0, 1.0)
    rules = TASK
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (judge_model_field(),)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        agent = ctx.agent_messages
        if not agent:
            return EvalOutcome.not_applicable("the agent never spoke")
        model = judge_model(settings, tools)
        scores, usage = await tools.judge.score_turns(
            model,
            task=TASK.format(goal=agent_goal(ctx)),
            messages=ctx.messages,
            turns=[m.index for m in agent],
        )
        items = [
            ItemResult(
                process_reward_verdict(s.score),
                float(s.score),
                s.rationale,
                turn_index=n,
                evidence={"turn_indices": [s.turn]},
            )
            for n, s in enumerate(scores, start=1)
        ]
        regressions = [i for i in items if i.verdict == "fail"]
        rationale = (
            f"{len(regressions)} of {len(items)} agent turns went backwards; first at turn {regressions[0].turn_index}: {regressions[0].rationale}"
            if regressions
            else f"No agent turn went backwards across {len(items)} turns."
        )
        return EvalOutcome(
            items,
            rationale=rationale,
            judge_model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            raw_cost_usd=usage.raw_cost_usd,
        )
