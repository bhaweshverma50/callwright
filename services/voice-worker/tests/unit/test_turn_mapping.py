"""T059: interruption and responsiveness mapping (research R4) and turn detection (R5)."""

from __future__ import annotations

import itertools

import pytest

from tests.unit.conftest import make_runtime
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.call_behavior import behavior_from_config, map_interruption, map_responsiveness
from worker.pipeline import plan_session, select_turn_detection, turn_handling_options

STEPS = [i / 20 for i in range(21)]


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
    d = map_responsiveness(0.79)
    assert d.min_endpointing_delay == pytest.approx(0.41)
    assert d.max_endpointing_delay == pytest.approx(2.445)
    params = [map_responsiveness(r) for r in STEPS]
    for low, high in itertools.pairwise(params):
        assert high.min_endpointing_delay < low.min_endpointing_delay
        assert high.max_endpointing_delay < low.max_endpointing_delay
    assert map_responsiveness(1.0).min_endpointing_delay == pytest.approx(0.2)


def test_out_of_range_values_clamp() -> None:
    assert map_interruption(7) == map_interruption(1)
    assert map_responsiveness(-1) == map_responsiveness(0)
    behavior = behavior_from_config(
        {"call_behavior": {"end_on_silence_s": 5, "max_duration_s": 9000, "responsiveness": 2}}
    )
    assert behavior.end_on_silence_s == 10
    assert behavior.max_duration_s == 3600
    assert {n.path for n in behavior.notes} == {
        "end_on_silence_s",
        "max_duration_s",
        "responsiveness",
    }


def test_claim_limits_win_over_config() -> None:
    behavior = behavior_from_config(
        {"call_behavior": {"end_on_silence_s": 30}}, {"end_on_silence_s": 60}
    )
    assert behavior.end_on_silence_s == 60


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
    behavior = behavior_from_config({"call_behavior": {"interruption_sensitivity": 0.9}})
    semantic = turn_handling_options(behavior, "semantic")
    assert set(semantic["endpointing"]) == {"min_delay", "max_delay"}
    assert semantic["interruption"]["enabled"] is True
    assert semantic["interruption"]["min_duration"] == pytest.approx(0.26)
    stt = turn_handling_options(behavior, "stt")
    assert set(stt["endpointing"]) == {"min_delay"}  # R4: only the minimum applies
    off = turn_handling_options(
        behavior_from_config({"call_behavior": {"interruption_sensitivity": 0}}), "semantic"
    )
    assert off["interruption"] == {"enabled": False}


def test_multi_language_uses_semantic_model() -> None:
    plan = plan_session(make_runtime({"language": "multi"}), AdapterRegistry())
    assert plan.stt.model == "nova-2"
    assert plan.turn_detection == "semantic"
