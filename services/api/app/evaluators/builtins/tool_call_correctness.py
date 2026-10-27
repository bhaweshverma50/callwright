"""``tool_call_correctness``: tool invocations were the right choices with the right inputs (judge)."""

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
    "Review every tool call the agent made (shown in parentheses after the line it followed). "
    "Score 1 when each call was needed at that point, used the right tool and passed arguments "
    "the caller actually gave, and the agent handled the result (including errors) correctly; "
    "0.5 when a call was unnecessary or an argument was doubtful; 0 when the agent used the "
    "wrong tool, invented arguments, or ignored a failed result."
)


class ToolCallCorrectness(Evaluator):
    name = "tool_call_correctness"
    display_name = "Tool call correctness"
    description = "Checks that the agent called the right tools, with arguments from the conversation."
    cost_class = "llm_judge"
    rules = TASK
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (judge_model_field(),)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not ctx.tools:
            return EvalOutcome.not_applicable("no tool calls")
        return await judge_call(ctx, settings, tools, TASK)
