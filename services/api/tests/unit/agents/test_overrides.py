"""validate_override and the shared controls table (T104, FR-047)."""

from __future__ import annotations

from app.agents.validation import validate_override


def test_in_range_values_pass_in_both_path_forms() -> None:
    assert validate_override("/tts/speed", 1.5) == []
    assert validate_override("tts.speed", 0.5) == []
    assert validate_override("call_behavior.ring_duration_ms", 1500) == []


def test_out_of_range_uses_control_label() -> None:
    (issue,) = validate_override("/tts/speed", 2.5)
    assert issue == {
        "pointer": "/tts/speed",
        "code": "out_of_range",
        "message": "Voice speed must be between 0.5 and 2x.",
    }
    (ring,) = validate_override("call_behavior.ring_duration_ms", -1)
    assert ring["pointer"] == "/call_behavior/ring_duration_ms"
    assert ring["message"] == "Ring time must be between 0 and 30,000 ms."


def test_unknown_path_and_bad_type() -> None:
    assert validate_override("/tts/stability", 0.5)[0]["code"] == "not_in_catalog"
    assert validate_override("/tts/speed", "fast")[0]["code"] == "invalid_format"
    assert validate_override("/tts/speed", True)[0]["code"] == "invalid_format"
