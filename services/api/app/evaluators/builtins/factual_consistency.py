"""``factual_consistency``: replies stay grounded in what the knowledge base returned (judge)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.evaluators.base import (
    EvalContext,
    EvalOutcome,
    EvalTools,
    Evaluator,
    SettingsField,
    judge_model_field,
)
from app.evaluators.builtins.common import judge_call

TASK = (
    "The agent searched its knowledge base during the call; the passages each search returned "
    "are shown as tool results. Score 1 when every factual statement the agent made after a "
    "search is supported by the returned passages, 0.5 when some statements go beyond them "
    "without contradicting them, and 0 when the agent contradicted the passages or invented "
    "facts (prices, policies, dates) they do not contain."
)


class FactualConsistency(Evaluator):
    name = "factual_consistency"
    display_name = "Factual consistency"
    description = "Checks that the agent's answers stay grounded in the knowledge-base passages it retrieved."
    cost_class = "llm_judge"
    rules = TASK
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (judge_model_field(),)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not ctx.kb_searches:
            return EvalOutcome.not_applicable("no knowledge-base search happened")
        return await judge_call(ctx, settings, tools, TASK)
