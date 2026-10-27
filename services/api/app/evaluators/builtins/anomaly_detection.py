"""``anomaly_detection``: distance from the agent's recent calls, without labels (FR-042, R13)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.evals.scoring import Verdict
from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult, SettingsField


class AnomalyDetection(Evaluator):
    name = "anomaly_detection"
    display_name = "Anomaly detection"
    description = (
        "Compares the call with the agent's recent calls and flags it when it is far from all of "
        "them. Needs no labels; finds problems nobody wrote a check for."
    )
    output_kind = "anomaly"
    threshold_direction = "above_fails"
    rules = "mean cosine distance to the knn_k nearest live calls of the agent within window_days"
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (
        SettingsField(
            "threshold",
            "Distance threshold",
            "number",
            0.7,
            min=0,
            max=1,
            step=0.05,
            helper=(
                "Calls whose mean distance to their nearest neighbours is above this are flagged. "
                "Default: {default}."
            ),
        ),
        SettingsField(
            "window_days",
            "Comparison window (days)",
            "int",
            30,
            min=1,
            max=365,
            step=1,
            helper="Compare with calls that ended in this many days. Default: {default}.",
        ),
        SettingsField(
            "min_sample_size",
            "Minimum comparable calls",
            "int",
            30,
            min=5,
            max=500,
            step=1,
            helper="Below this many comparable calls the check reads insufficient data. Default: {default}.",
        ),
        SettingsField(
            "knn_k",
            "Neighbours",
            "int",
            10,
            min=1,
            max=50,
            step=1,
            helper="How many nearest calls the distance is averaged over. Default: {default}.",
        ),
        SettingsField(
            "backfill_per_run",
            "Backfill per run",
            "int",
            5,
            min=0,
            max=20,
            step=1,
            helper=(
                "Older calls prepared for comparison on each run; 0 turns backfill off. Default: {default}."
            ),
        ),
    )

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if not ctx.messages:
            return EvalOutcome.not_applicable("no conversation to compare")
        if tools.neighbours is None:
            return EvalOutcome.not_applicable("insufficient data")
        found = await tools.neighbours(ctx, settings)
        minimum = int(settings["min_sample_size"])
        if found.comparable < minimum or not found.distances:
            reason = f"insufficient data ({found.comparable} of {minimum} comparable calls)"
            return EvalOutcome.not_applicable(reason)
        distances = list(found.distances)
        score = sum(distances) / len(distances)
        threshold = float(settings["threshold"])
        verdict: Verdict = "fail" if score > threshold else "pass"
        side = "above" if verdict == "fail" else "within"
        rationale = (
            f"Mean distance {score:.2f} to the {len(distances)} nearest calls is {side} the "
            f"{threshold:.2f} threshold ({found.comparable} comparable calls in "
            f"{settings['window_days']} days)."
        )
        item = ItemResult(verdict, round(score, 4), rationale, evidence={"neighbours": len(distances)})
        return EvalOutcome([item], rationale=rationale)
