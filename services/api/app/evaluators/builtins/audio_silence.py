"""``audio_silence``: long silences heard in the recording, not the transcript (FR-040, R12)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.evaluators.audio import RecordingUnavailable, Silence, find_silences
from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult, SettingsField


def clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def silence_outcome(silences: list[Silence], settings: Mapping[str, Any]) -> EvalOutcome:
    limit = int(settings["max_acceptable_silence_ms"])
    longest = sorted(silences, key=lambda s: (-s.duration_ms, s.start_ms))[:3]
    if not longest:
        rationale = (
            f"No silence of {int(settings['min_silence_ms']):,} ms or more between the first and last sound."
        )
        item = ItemResult("pass", 0.0, rationale)
        return EvalOutcome([item], rationale=rationale)
    top = longest[0]
    listed = "; ".join(f"{s.duration_ms:,} ms at {clock(s.start_ms)}" for s in longest)
    verdict = "fail" if top.duration_ms > limit else "pass"
    side = "over" if verdict == "fail" else "within"
    rationale = f"Longest silence {top.duration_ms:,} ms at {clock(top.start_ms)} is {side} the {limit:,} ms limit. Longest: {listed}."
    item = ItemResult(
        verdict,
        float(top.duration_ms),
        rationale,
        start_ms=top.start_ms,
        duration_ms=top.duration_ms,
        evidence={"silences": [{"start_ms": s.start_ms, "duration_ms": s.duration_ms} for s in longest]},
    )
    return EvalOutcome([item], rationale=rationale)


class AudioSilence(Evaluator):
    name = "audio_silence"
    display_name = "Long silences"
    description = "Listens to the call recording for stretches where nobody spoke (dead air, stalls)."
    output_kind = "audio_quality"
    enabled_by_default = True
    score_range = (0.0, 60_000.0)
    rules = "frames silent on both channels below average + threshold; runs >= min_silence_ms; fail above max"
    settings_fields: ClassVar[tuple[SettingsField, ...]] = (
        SettingsField(
            "max_acceptable_silence_ms",
            "Maximum silence (ms)",
            "int",
            3000,
            min=500,
            max=60_000,
            step=100,
            helper="A silence longer than this fails the check. Default: {default} ms.",
        ),
        SettingsField(
            "silence_threshold_db",
            "Silence level (dB below average)",
            "number",
            -40,
            min=-80,
            max=-10,
            step=1,
            helper="Quieter than the call's average level by this much counts as silence. Default: {default} dB.",
        ),
        SettingsField(
            "min_silence_ms",
            "Shortest silence counted (ms)",
            "int",
            1000,
            min=200,
            max=10_000,
            step=100,
            helper="Pauses shorter than this are ignored. Default: {default} ms.",
        ),
    )

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        if ctx.recording is None or ctx.origin == "simulation" or tools.read_levels is None:
            return EvalOutcome.not_applicable("no recording")
        try:
            levels = await tools.read_levels(ctx.recording)
        except RecordingUnavailable as exc:
            return EvalOutcome.not_applicable(f"no recording ({exc})")
        silences = find_silences(
            levels,
            threshold_db=float(settings["silence_threshold_db"]),
            min_silence_ms=int(settings["min_silence_ms"]),
        )
        return silence_outcome(silences, settings)
