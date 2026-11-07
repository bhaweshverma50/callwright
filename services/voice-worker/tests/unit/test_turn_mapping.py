"""T059: interruption and responsiveness mapping (research R4) and turn detection (R5)."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from callwright_contract.protocol import Limits

from tests.unit.conftest import make_runtime
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.call_behavior import (
    VAD_MIN_SILENCE_S,
    CallBehavior,
    behavior_from_config,
    map_interruption,
    map_responsiveness,
)
from worker.pipeline import plan_session, select_turn_detection, turn_handling_options

STEPS = [i / 20 for i in range(21)]


def behavior_for(limits: dict[str, int] | None = None, **call_behavior: Any) -> CallBehavior:
    runtime = make_runtime({"call_behavior": call_behavior})
    claimed = Limits(**{**runtime.limits.model_dump(), **(limits or {})})
    return behavior_from_config(runtime.config, claimed, runtime.controls)


def test_interruption_formulas_at_reference_points() -> None:
    p = map_interruption(0.95)
    assert p.allow_interruptions and p.min_interruption_words == 0
    assert p.min_interruption_duration == pytest.approx(0.23)
    mid = map_interruption(0.5)
    assert mid.min_interruption_duration == pytest.approx(0.5)  # framework default
    assert mid.min_interruption_words == 1
    assert map_interruption(0.29).min_interruption_words == 2
    assert map_interruption(0.3).min_interruption_words == 1
    assert map_interruption(0.7).min_interruption_words == 0


def test_zero_sensitivity_disables_interruptions() -> None:
    assert not map_interruption(0).allow_interruptions
    assert map_interruption(0.05).allow_interruptions


def test_interruption_is_monotonic() -> None:
    params = [map_interruption(s) for s in STEPS]
    for low, high in itertools.pairwise(params):
        assert high.min_interruption_duration <= low.min_interruption_duration
        assert high.min_interruption_words <= low.min_interruption_words


def test_responsiveness_formulas_and_monotonicity() -> None:
    d = map_responsiveness(0.8)  # the 002 default
    assert d.min_endpointing_delay == pytest.approx(0.4)
    assert d.max_endpointing_delay == pytest.approx(1.22)
    assert d.preemptive_tts
    params = [map_responsiveness(r) for r in STEPS]
    for low, high in itertools.pairwise(params):
        assert high.min_endpointing_delay < low.min_endpointing_delay
        assert high.max_endpointing_delay < low.max_endpointing_delay
    fastest, slowest = map_responsiveness(1.0), map_responsiveness(0.0)
    assert fastest.min_endpointing_delay == pytest.approx(VAD_MIN_SILENCE_S)
    assert fastest.max_endpointing_delay == pytest.approx(0.9)
    assert slowest.min_endpointing_delay == pytest.approx(0.8)
    assert slowest.max_endpointing_delay == pytest.approx(2.5)


def test_endpointing_never_undercuts_the_vad_floor() -> None:
    """A min delay under the VAD silence window would have no effect (R4)."""
    assert 0.25 <= VAD_MIN_SILENCE_S <= 0.55  # audio detector minimum, framework default
    for r in STEPS:
        d = map_responsiveness(r)
        assert d.min_endpointing_delay >= VAD_MIN_SILENCE_S
        # The unfinished-turn wait always outlasts the finished-turn wait by at least 0.5 s,
        # so a caller pausing mid-sentence has room to go on.
        assert d.max_endpointing_delay - d.min_endpointing_delay >= 0.5


def test_out_of_range_values_clamp() -> None:
    assert map_interruption(7) == map_interruption(1)
    assert map_responsiveness(-1) == map_responsiveness(0)
    behavior = behavior_for({"end_on_silence_s": 5, "max_duration_s": 9000}, responsiveness=2)
    assert behavior.end_on_silence_s == 10
    assert behavior.max_duration_s == 3600
    assert {n.path for n in behavior.notes} == {
        "/call_behavior/end_on_silence_s",
        "/call_behavior/max_duration_s",
        "/call_behavior/responsiveness",
    }


def test_claim_limits_win_over_config() -> None:
    assert behavior_for({"end_on_silence_s": 60}, end_on_silence_s=30).end_on_silence_s == 60


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("deepgram", "flux-general-en", "stt"),
        ("assemblyai", "universal-streaming", "stt"),
        ("assemblyai", "universal-streaming-multilingual", "stt"),
        ("deepgram", "nova-3", "semantic"),
        ("deepgram", "nova-2", "semantic"),
        ("sarvam", "saarika:v2.5", "semantic"),
    ],
)
def test_turn_detection_selection(provider: str, model: str, expected: str) -> None:
    assert select_turn_detection(VendorSpec("stt", provider, model), AdapterRegistry()) == expected


def test_turn_handling_options_shape() -> None:
    behavior = behavior_for(interruption_sensitivity=0.9)
    semantic = turn_handling_options(behavior, "semantic")
    assert semantic["endpointing"]["mode"] == "fixed"
    assert set(semantic["endpointing"]) == {"mode", "min_delay", "max_delay"}
    assert semantic["interruption"]["enabled"] is True
    assert semantic["interruption"]["min_duration"] == pytest.approx(0.26)
    assert semantic["interruption"]["resume_false_interruption"] is True
    assert semantic["interruption"]["false_interruption_timeout"] == pytest.approx(1.0)
    assert semantic["preemptive_generation"] == {"enabled": True, "preemptive_tts": True}
    stt = turn_handling_options(behavior, "stt")
    assert set(stt["endpointing"]) == {"mode", "min_delay"}  # R4: only the minimum applies
    off = turn_handling_options(behavior_for(interruption_sensitivity=0), "semantic")
    assert off["interruption"] == {"enabled": False}


def test_multi_language_uses_semantic_model() -> None:
    plan = plan_session(make_runtime({"language": "multi"}), AdapterRegistry())
    assert plan.stt.model == "nova-3"  # the speech catalog's rule, as admission picked
    assert plan.turn_detection == "semantic"
