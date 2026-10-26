"""Catalog and tool references (004 T074, T114)."""

from __future__ import annotations

from app.flows.catalogs import check_overrides
from app.flows.validation import ValidationContext, validate
from tests.flow_helpers import clinic, codes

TOOL = "tool_01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_known_overrides_pass() -> None:
    assert check_overrides({"llm": {"provider": "openai", "model": "gpt-5-mini", "temperature": 1.0}}) == []
    assert (
        check_overrides(
            {"tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5", "voice_id": "x", "speed": 1.1}}
        )
        == []
    )
    assert check_overrides({"stt": {"provider": "deepgram", "model": "nova-3"}, "language": "es"}) == []


def test_unknown_catalog_entries() -> None:
    fields = {
        f
        for _, f, _ in check_overrides(
            {
                "llm": {"provider": "openai", "model": "gpt-0"},
                "tts": {"provider": "nobody", "voice_id": "x"},
                "stt": {"provider": "deepgram", "model": "nova-0"},
                "language": "xx-XX",
            }
        )
    }
    assert fields == {"llm.model", "tts.provider", "stt.model", "language"}


def test_ranges_come_from_the_shared_controls_table() -> None:
    problems = check_overrides(
        {"tts": {"provider": "elevenlabs", "voice_id": "x", "speed": 3.0, "volume": -1}}
    )
    assert {(c, f) for c, f, _ in problems} == {
        ("E_INVALID_FIELD", "tts.speed"),
        ("E_INVALID_FIELD", "tts.volume"),
    }


def test_fixed_temperature_models() -> None:
    problems = check_overrides({"llm": {"provider": "openai", "model": "gpt-5.1", "temperature": 0.2}})
    assert problems and problems[0][1] == "llm.temperature" and "1.0" in problems[0][2]


def test_unknown_catalog_is_a_publish_error_on_the_node() -> None:
    g = clinic()
    g["nodes"][1]["config"]["overrides"]["tts"] = {"provider": "nobody", "voice_id": "x"}
    issue = next(
        i
        for i in validate(g, ValidationContext(check_overrides=check_overrides))
        if i["code"] == "E_UNKNOWN_CATALOG"
    )
    assert issue["node_id"] == "n_triage01" and issue["field"] == "overrides.tts.provider"


def test_unknown_and_duplicate_tools() -> None:
    g = clinic()
    g["nodes"][1]["config"]["tool_ids"] = [TOOL, "tool_01ARZ3NDEKTSV4RRFFQ69G5FA9"]
    issues = validate(g, ValidationContext(tools={TOOL: "lookup"}, flow_tool_names=("lookup",)))
    assert codes(issues).count("E_UNKNOWN_TOOL") == 1
    assert "E_FUNCTION_NAME_CLASH" in codes(issues)
