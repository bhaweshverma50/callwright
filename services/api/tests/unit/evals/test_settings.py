"""Effective settings and validation (007 T026, T080; FR-036, FR-038). The headline limit runs
against the database in tests/contract/test_evals_contract.py."""

from __future__ import annotations

from app.evals.settings import effective, fmt, served_schema, validate_overrides
from app.evaluators.registry import BUILTINS, schema_json

MODELS = ["openai/gpt-5-mini", "azure_openai/gpt-5.1"]


def schema(name: str) -> dict:  # type: ignore[type-arg]
    return served_schema(schema_json(BUILTINS[name].settings_fields), MODELS)


def errors(name: str, overrides: object) -> dict[str, str]:
    return {e["pointer"]: e["message"] for e in validate_overrides(schema(name), overrides)}


def test_sample_rate_150_rejected_with_field_message() -> None:
    assert errors("intent_fulfillment", {"sample_rate_pct": 150}) == {
        "/overrides/sample_rate_pct": "Enter a whole number from 1 to 100"
    }


def test_int_rejects_decimals_and_bools() -> None:
    assert "/overrides/max_visits_per_node" in errors("stuck_loop_detector", {"max_visits_per_node": 2.5})
    assert "/overrides/max_visits_per_node" in errors("stuck_loop_detector", {"max_visits_per_node": True})
    assert errors("stuck_loop_detector", {"max_visits_per_node": 4.0}) == {}
    assert errors("stuck_loop_detector", {"max_visits_per_node": 11}) == {
        "/overrides/max_visits_per_node": "Enter a whole number from 2 to 10"
    }


def test_number_range_and_thousands() -> None:
    assert errors("anomaly_detection", {"threshold": 0.35}) == {}
    assert errors("anomaly_detection", {"threshold": 1.2}) == {
        "/overrides/threshold": "Enter a number from 0 to 1"
    }
    assert errors("audio_silence", {"max_acceptable_silence_ms": 70000}) == {
        "/overrides/max_acceptable_silence_ms": "Enter a whole number from 500 to 60,000"
    }


def test_judge_model_must_be_in_list() -> None:
    assert errors("intent_fulfillment", {"judge_model": "azure_openai/gpt-5.1"}) == {}
    assert errors("intent_fulfillment", {"judge_model": "my-own-model"}) == {
        "/overrides/judge_model": "Pick one of the listed judge models"
    }


def test_unknown_key_rejected() -> None:
    assert errors("latency_slo", {"pass_threshold": 0.5}) == {
        "/overrides/pass_threshold": "Unknown setting pass_threshold"
    }
    assert errors("flow_completion", {"anything": 1}) != {}


def test_served_schema_fills_judge_models_and_helper_defaults() -> None:
    fields = {f["key"]: f for f in schema("intent_fulfillment")["fields"]}
    assert fields["judge_model"]["options"] == MODELS and fields["judge_model"]["default"] == MODELS[0]
    assert fields["judge_model"]["type"] == "select"
    silence = {f["key"]: f for f in schema("audio_silence")["fields"]}
    assert silence["max_acceptable_silence_ms"]["helper"].endswith("Default: 3,000 ms.")
    assert silence["max_acceptable_silence_ms"]["default"] == 3000
    assert "{default}" not in str(schema("anomaly_detection"))


def test_effective_overlays_and_clamps() -> None:
    values, adjusted = effective(schema("stuck_loop_detector"), {"max_visits_per_node": 5})
    assert values == {"max_visits_per_node": 5} and adjusted == []
    values, adjusted = effective(schema("stuck_loop_detector"), {"max_visits_per_node": 40})
    assert values == {"max_visits_per_node": 10} and adjusted == ["max_visits_per_node"]
    values, adjusted = effective(schema("intent_fulfillment"), {"judge_model": "retired/model"})
    assert values["judge_model"] == MODELS[0] and adjusted == ["judge_model"]
    values, _ = effective(schema("intent_fulfillment"), None)
    assert values == {"judge_model": MODELS[0], "sample_rate_pct": 100}


def test_fmt() -> None:
    assert (fmt(3000), fmt(0.7), fmt(-40), fmt(1)) == ("3,000", "0.7", "-40", "1")
