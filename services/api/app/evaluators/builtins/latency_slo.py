"""``latency_slo``: agent turns slower than the threshold (FR-041)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.calls.origins import policy
from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult, SettingsField


class LatencySlo(Evaluator):
    name = "latency_slo"
    display_name = "Turn latency"
    description = (
        "Flags agent turns that took longer than the threshold from the end of the caller's "
        "speech to the first agent audio."
    )
    scope = "turn"
    enabled_by_default = True
    score_range = (0.0, 30_000.0)
    rules = "one item per agent turn with audio timing; fail when e2e_ms > threshold_ms"
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (
        SettingsField(
            "threshold_ms",
            "Latency threshold (ms)",
            "int",
            3000,
            min=100,
            max=30_000,
            step=100,
            helper="A reply slower than this fails the turn. Default: {default} ms.",
        ),
    )

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not policy(ctx.origin).has_real_audio or not ctx.latencies:
            return EvalOutcome.not_applicable("no audio timing")
        limit = int(settings["threshold_ms"])
        items = []
        for t in sorted(ctx.latencies, key=lambda x: x.turn_index):
            slow = t.e2e_ms > limit
            items.append(
                ItemResult(
                    "fail" if slow else "pass",
                    float(t.e2e_ms),
                    (
                        f"Turn {t.turn_index} answered in {t.e2e_ms:,} ms ({'over' if slow else 'within'} "
                        f"{limit:,} ms)."
                    ),
                    turn_index=t.turn_index,
                )
            )
        slow_items = [i for i in items if i.verdict == "fail"]
        rationale = (
            (
                f"{len(slow_items)} of {len(items)} turns were slower than {limit:,} ms; slowest "
                f"{max(i.score or 0 for i in slow_items):,.0f} ms."
            )
            if slow_items
            else f"All {len(items)} turns answered within {limit:,} ms."
        )
        return EvalOutcome(items, rationale=rationale)
