"""``llm_judge_custom``: a yes/no question about the call answered by a judge model (FR-009).

The judge scores 1 for yes and 0 for no; the server reads yes when the score is at least the
cutoff and passes the run when the answer equals ``pass_when``. The run's score is 1 for a pass
and 0 for a fail, so pass rates read the same as for every other check.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult

TASK = (
    "QUESTION: {question}\n"
    "Answer the question about this call from what was said. Score 1 if the answer is yes and 0 "
    "if it is no. In the rationale, start with Yes or No and quote the line that decides it."
)


class LlmJudgeCustom(Evaluator):
    name = "llm_judge_custom"
    display_name = "Custom judge question"
    description = "Asks a judge model a yes or no question about the call."
    cost_class = "llm_judge"

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not ctx.messages:
            return EvalOutcome.not_applicable("no conversation was recorded")
        model = str(self.config.get("judge_model") or tools.judge_model)
        result = await tools.judge.score_call(
            model, task=TASK.format(question=self.config["question"]), messages=ctx.messages, tools=ctx.tools
        )
        j = result.judgement
        answer = "yes" if j.score >= tools.cutoff else "no"
        passed = answer == str(self.config.get("pass_when") or "yes")
        item = ItemResult(
            "pass" if passed else "fail",
            1.0 if passed else 0.0,
            j.rationale,
            evidence={"turn_indices": j.evidence_turns, "quote": j.quote, "answer": answer},
        )
        return EvalOutcome(
            [item],
            rationale=j.rationale,
            judge_model=model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            raw_cost_usd=result.usage.raw_cost_usd,
        )
