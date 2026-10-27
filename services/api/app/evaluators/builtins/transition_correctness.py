"""``transition_correctness``: each transition took the right edge (judge, FR-043).

Map step: one judge call per transition with the source node's alternatives in an order
shuffled with the run id as seed (position bias). Reduce: one item per transition, attributed
to its source node.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar

from app.evaluators.base import (
    FLOW_ONLY,
    EvalContext,
    EvalOutcome,
    EvalTools,
    Evaluator,
    ItemResult,
    SettingsField,
    judge_model_field,
)
from app.evaluators.builtins.common import judge_model

TASK = (
    "The agent was at the flow step described below and had to choose where to go next. Decide "
    "from the conversation so far whether the edge it took was the right one among the "
    "alternatives. Score 1 when it was right, 0.5 when another edge was about as good, 0 when "
    "another edge was clearly right.\n\nSTEP: {label}\nSTEP INSTRUCTIONS: {instructions}\n"
    "ALTERNATIVES:\n{alternatives}\nTAKEN: {taken}"
)


def alternatives(node: Mapping[str, Any]) -> list[dict[str, str]]:
    out = []
    for t in node.get("transitions") or []:
        if isinstance(t, Mapping):
            out.append(
                {
                    "target": str(t.get("target_node_id") or ""),
                    "text": str(t.get("label") or t.get("description") or t.get("function_name") or "next"),
                }
            )
    return out


class TransitionCorrectness(Evaluator):
    name = "transition_correctness"
    display_name = "Transition correctness"
    description = "Judges each step change in the flow against the other edges the agent could have taken."
    cost_class = "llm_judge"
    agent_types = FLOW_ONLY
    rules = TASK
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (judge_model_field(),)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not ctx.transitions:
            return EvalOutcome.not_applicable("no flow transitions")
        model = judge_model(settings, tools)
        rng = random.Random(ctx.run_id or ctx.call_id)  # noqa: S311 (position shuffle, not security)
        items: list[ItemResult] = []
        tokens_in = tokens_out = 0
        cost = Decimal(0)
        for t in ctx.transitions:
            source = t.from_node_id
            node = ctx.flow_nodes.get(source or "") or {}
            options = alternatives(node)
            label = ctx.node_label(source) or "start"
            if len(options) < 2:
                items.append(
                    ItemResult(
                        "not_applicable",
                        None,
                        f'"{label}" had only one way forward.',
                        flow_node_id=source,
                        flow_node_label=label,
                    )
                )
                continue
            rng.shuffle(options)
            listing = "\n".join(f"- to {ctx.node_label(o['target'])}: {o['text']}" for o in options)
            taken = f"to {ctx.node_label(t.to_node_id)}" + (f": {t.label}" if t.label else "")
            task = TASK.format(
                label=label,
                instructions=str(node.get("instructions") or "")[:1500],
                alternatives=listing,
                taken=taken,
            )
            result = await tools.judge.score_call(model, task=task, messages=ctx.messages, tools=ctx.tools)
            j = result.judgement
            tokens_in += result.usage.input_tokens
            tokens_out += result.usage.output_tokens
            cost += result.usage.raw_cost_usd
            items.append(
                ItemResult(
                    j.verdict,
                    j.score,
                    j.rationale,
                    flow_node_id=source,
                    flow_node_label=label,
                    evidence={"turn_indices": j.evidence_turns, "quote": j.quote, "to_node_id": t.to_node_id},
                )
            )
        failed = [i for i in items if i.verdict == "fail"]
        rationale = (
            (
                f"{len(failed)} of {len(items)} transitions took the wrong edge; first at "
                f'"{failed[0].flow_node_label}": {failed[0].rationale}'
            )
            if failed
            else f"Every judged transition took a right edge ({len(items)} transitions)."
        )
        return EvalOutcome(
            items,
            rationale=rationale,
            judge_model=model if tokens_in else None,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            raw_cost_usd=cost,
        )
