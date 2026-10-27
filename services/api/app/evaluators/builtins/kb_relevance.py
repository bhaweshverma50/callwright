"""``kb_relevance``: knowledge-base searches returned content that addressed the question (judge)."""

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
    "For each knowledge-base search (tool kb_search) in the call, compare the caller's question "
    "that led to it with the passages it returned. Score 1 when the passages addressed the "
    "questions, 0.5 when they were partly relevant, 0 when they were unrelated or empty."
)


def has_knowledge_base(config: Mapping[str, Any]) -> bool:
    if config.get("kb_ids"):
        return True
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    nodes = compiled.get("nodes") if isinstance(compiled, Mapping) else None
    return isinstance(nodes, Mapping) and any(
        isinstance(n, Mapping) and n.get("kb_search") for n in nodes.values()
    )


class KbRelevance(Evaluator):
    name = "kb_relevance"
    display_name = "Knowledge retrieval relevance"
    description = "Checks that knowledge-base searches returned passages that answer the caller's question."
    cost_class = "llm_judge"
    rules = TASK
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (judge_model_field(),)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not has_knowledge_base(ctx.config):
            return EvalOutcome.not_applicable("the agent has no knowledge base")
        if not ctx.kb_searches:
            return EvalOutcome.not_applicable("no knowledge-base search happened")
        return await judge_call(ctx, settings, tools, TASK, tool_events=ctx.kb_searches)
