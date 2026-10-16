"""AgentConfig v1 structure and ranges (T005, data-model.md section 4, SC-004)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.agents.defaults import default_config
from app.agents.schemas import AgentConfigV1, upcast
from app.agents.validation import validate_pure


def config(**changes: Any) -> dict[str, Any]:
    base = default_config("single_prompt")
    base["prompt"] = "You answer calls for a dental clinic."
    for path, value in changes.items():
        node = base
        parts = path.split("__")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return base


def pointers(result: Any) -> set[str]:
    return {e["pointer"] for e in result.errors}


def test_defaults_are_valid() -> None:
    result = validate_pure("single_prompt", config())
    assert result.valid, result.errors
    AgentConfigV1.model_validate(result.normalized_config)


def test_blank_flow_defaults_are_valid() -> None:
    result = validate_pure("flow", default_config("flow"))
    assert result.valid, result.errors


# (path, bad value, expected pointer, ok value)
RANGES = [
    ("tts__speed", 0.4, "/tts/speed", 2.0),
    ("tts__speed", 2.1, "/tts/speed", 0.5),
    ("tts__expressiveness", -0.1, "/tts/expressiveness", 2.0),
    ("tts__expressiveness", 2.1, "/tts/expressiveness", 0),
    ("tts__volume", 2.05, "/tts/volume", 2.0),
    ("call_behavior__end_on_silence_s", 9, "/call_behavior/end_on_silence_s", 300),
    ("call_behavior__end_on_silence_s", 301, "/call_behavior/end_on_silence_s", 10),
    ("call_behavior__max_duration_s", 12, "/call_behavior/max_duration_s", 30),
    ("call_behavior__max_duration_s", 3660, "/call_behavior/max_duration_s", 3600),
    ("call_behavior__ring_duration_ms", -1, "/call_behavior/ring_duration_ms", 0),
    ("call_behavior__ring_duration_ms", 30001, "/call_behavior/ring_duration_ms", 30000),
    ("call_behavior__interruption_sensitivity", 1.1, "/call_behavior/interruption_sensitivity", 1),
    ("call_behavior__responsiveness", -0.5, "/call_behavior/responsiveness", 0),
    ("advanced__webhook_timeout_ms", 50, "/advanced/webhook_timeout_ms", 1000),
    ("advanced__webhook_timeout_ms", 30001, "/advanced/webhook_timeout_ms", 30000),
    ("advanced__dtmf__timeout_ms", 999, "/advanced/dtmf/timeout_ms", 10000),
    ("advanced__dtmf__digits", 0, "/advanced/dtmf/digits", 99),
    ("advanced__dtmf__digits", 100, "/advanced/dtmf/digits", 1),
    ("advanced__background_audio__volume", 3.05, "/advanced/background_audio/volume", 3),
    ("prompt", "x" * 50_001, "/prompt", "x" * 50_000),
    ("begin_message", "x" * 1_001, "/begin_message", "x" * 1_000),
]


@pytest.mark.parametrize(("path", "bad", "pointer", "ok"), RANGES)
def test_ranges(path: str, bad: Any, pointer: str, ok: Any) -> None:
    result = validate_pure("single_prompt", config(**{path: bad}))
    assert pointer in pointers(result)
    issue = next(e for e in result.errors if e["pointer"] == pointer)
    assert issue["code"] == "out_of_range"
    assert issue["message"]
    assert validate_pure("single_prompt", config(**{path: ok})).valid


@pytest.mark.parametrize(
    ("path", "bad", "pointer"),
    [
        ("start_speaker", "bot", "/start_speaker"),
        ("advanced__dtmf__termination_key", "x", "/advanced/dtmf/termination_key"),
        ("advanced__voicemail_detection__action", "shout", "/advanced/voicemail_detection/action"),
        ("advanced__recording", "always", "/advanced/recording"),
        ("call_behavior__max_duration_s", "ten", "/call_behavior/max_duration_s"),
        ("call_behavior__max_duration_s", 600.5, "/call_behavior/max_duration_s"),
    ],
)
def test_enums_and_types(path: str, bad: Any, pointer: str) -> None:
    result = validate_pure("single_prompt", config(**{path: bad}))
    assert pointer in pointers(result)
    assert next(e for e in result.errors if e["pointer"] == pointer)["code"] == "invalid_format"


def test_required_fields() -> None:
    cfg = config(prompt="", tts__voice_id="")
    cfg["tts"].pop("model")
    result = validate_pure("single_prompt", cfg)
    codes = {e["pointer"]: e["code"] for e in result.errors}
    assert codes["/prompt"] == "required"
    assert codes["/tts/voice_id"] == "required"


def test_flow_prompt_may_be_empty() -> None:
    assert validate_pure("flow", {**default_config("flow"), "prompt": ""}).valid


def test_lists_limits() -> None:
    cfg = config(tool_ids=[f"tool_{i}" for i in range(26)], kb_ids=[f"kb_{i}" for i in range(11)])
    cfg["dynamic_variables"] = [{"name": f"v{i}", "default": "x"} for i in range(51)]
    cfg["advanced"]["pronunciation"] = [{"word": f"w{i}", "replacement": "r"} for i in range(201)]
    found = pointers(validate_pure("single_prompt", cfg))
    assert {"/tool_ids", "/kb_ids", "/dynamic_variables", "/advanced/pronunciation"} <= found


def test_unknown_setting_is_refused() -> None:
    cfg = config()
    cfg["advanced"]["shout"] = True
    result = validate_pure("single_prompt", cfg)
    assert {"pointer": "/advanced/shout", "code": "unknown_field"} in [
        {k: e[k] for k in ("pointer", "code")} for e in result.errors
    ]


def test_all_errors_in_one_pass() -> None:
    cfg = config(
        prompt="",
        tts__voice_id="",
        call_behavior__ring_duration_ms=-1,
        call_behavior__max_duration_s=12,
        advanced__webhook_url="ftp://x",
        advanced__webhook_timeout_ms=50,
    )
    result = validate_pure("single_prompt", cfg)
    assert {
        "/prompt",
        "/tts/voice_id",
        "/call_behavior/ring_duration_ms",
        "/call_behavior/max_duration_s",
        "/advanced/webhook_url",
        "/advanced/webhook_timeout_ms",
    } <= pointers(result)
    assert not result.valid


def test_normalized_config_stays_well_formed_with_errors() -> None:
    result = validate_pure("single_prompt", config(call_behavior__ring_duration_ms=-1, tts="voice"))
    AgentConfigV1.model_validate(result.normalized_config)
    assert result.normalized_config["call_behavior"]["ring_duration_ms"] == 5000


def test_partial_config_is_overlaid_on_defaults() -> None:
    result = validate_pure("single_prompt", {"prompt": "Hi", "language": "hi"})
    assert result.valid, result.errors
    assert result.normalized_config["stt"] == {"provider": "sarvam", "model": None}
    assert result.normalized_config["call_behavior"]["max_duration_s"] == 600


def test_snapshot_only_blocks_never_reach_the_draft() -> None:
    result = validate_pure("single_prompt", {**config(), "tools": [{"tool_id": "tool_x"}], "knowledge": []})
    assert "tools" not in result.normalized_config and "knowledge" not in result.normalized_config


def test_upcast_reads_missing_recording_as_inherit() -> None:
    old = copy.deepcopy(config())
    del old["advanced"]["recording"]
    assert upcast(old)["advanced"]["recording"] == "inherit"
    assert "recording" not in old["advanced"], "upcast must not mutate stored configs"


def test_unsupported_schema_version() -> None:
    result = validate_pure("single_prompt", {**config(), "schema_version": 9})
    assert "/schema_version" in pointers(result)
