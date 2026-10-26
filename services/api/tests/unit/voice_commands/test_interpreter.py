"""Voice command interpretation and server validation (006 T073, FR-030, FR-031, SC-007)."""

from __future__ import annotations

from typing import Any

import pytest

from app.voice_commands.interpreter import keyword_interpret, validate
from app.voice_commands.schemas import InterpretRequest

SAVE = {"key": "save_flow", "label": "Save the flow", "params_schema": None}
FILTER = {
    "key": "filter_calls",
    "label": "Filter calls",
    "params_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "array", "items": {"type": "string", "enum": ["failed", "completed"]}}
        },
        "additionalProperties": False,
    },
}


def req(
    transcript: str, route: str = "/dashboard", actions: list[dict[str, Any]] | None = None, **extra: Any
) -> InterpretRequest:
    return InterpretRequest.model_validate(
        {
            "transcript": transcript,
            "visual_state": {
                "current_route": route,
                "page_title": "Dashboard",
                "current_datetime": "2026-10-16T10:00:00Z",
                "timezone": "UTC",
                "available_actions": actions or [],
                "highlightable_elements": ["period_picker", "refresh"],
                **extra,
            },
        }
    )


def test_unknown_route_downgrades_to_decline() -> None:
    result, downgraded = validate({"action": "navigate", "target": "/admin/secrets"}, req("go to secrets"))
    assert downgraded and result["action"] == "decline" and result["fallback_suggestion"]


def test_known_route_with_query_string_is_kept_clean() -> None:
    result, downgraded = validate(
        {
            "action": "navigate",
            "target": "/calls",
            "params": {"status": ["failed"], "date_range": "yesterday"},
        },
        req("x"),
    )
    assert (
        not downgraded
        and result["target"] == "/calls"
        and result["params"] == {"status": ["failed"], "date_range": "yesterday"}
    )


def test_navigate_params_are_filtered() -> None:
    result, _ = validate(
        {"action": "navigate", "target": "/calls", "params": {"status": ["failed", "boom"], "evil": "x"}},
        req("x"),
    )
    assert result["params"] == {"status": ["failed"]}


def test_unregistered_action_downgrades() -> None:
    result, downgraded = validate(
        {"action": "ui_action", "target": "delete_agent"}, req("delete this agent", actions=[SAVE])
    )
    assert downgraded and result["action"] == "decline"


def test_registered_action_with_bad_params_downgrades() -> None:
    bad, downgraded = validate(
        {"action": "ui_action", "target": "filter_calls", "params": {"status": ["exploded"]}},
        req("x", actions=[FILTER]),
    )
    assert downgraded and bad["action"] == "decline"
    good, downgraded = validate(
        {"action": "ui_action", "target": "filter_calls", "params": {"status": ["failed"]}},
        req("x", actions=[FILTER]),
    )
    assert not downgraded and good["params"] == {"status": ["failed"]}


def test_unknown_copilot_target_downgrades() -> None:
    result, downgraded = validate(
        {"action": "route_to_copilot", "target": "shell", "query": "rm -rf"}, req("x")
    )
    assert downgraded and result["action"] == "decline"


def test_highlight_must_be_a_registered_key() -> None:
    result, _ = validate(
        {"action": "decline", "highlight_element": "#app > div", "fallback_suggestion": "Try the menu"},
        req("x"),
    )
    assert result["highlight_element"] is None
    result, _ = validate({"action": "decline", "highlight_element": "refresh"}, req("x"))
    assert result["highlight_element"] == "refresh"


def test_unknown_action_downgrades() -> None:
    result, downgraded = validate({"action": "run_shell", "target": "ls"}, req("x"))
    assert downgraded and result["action"] == "decline"


@pytest.mark.parametrize(
    ("transcript", "action", "target"),
    [
        ("show me failed calls from yesterday", "navigate", "/calls"),
        ("go to billing", "navigate", "/billing"),
        ("open the agents page", "navigate", "/agents"),
        (
            "open the analytics assistant and ask what our busiest day was",
            "route_to_copilot",
            "analytics_chat",
        ),
        ("what page am I on", "answer", None),
        ("delete this agent", "decline", None),
    ],
)
def test_keyword_interpreter(transcript: str, action: str, target: str | None) -> None:
    raw = keyword_interpret(req(transcript))
    result, _ = validate(raw, req(transcript))
    assert result["action"] == action
    if target:
        assert result["target"] == target


def test_failed_calls_from_yesterday_params() -> None:
    raw = keyword_interpret(req("show me failed calls from yesterday"))
    assert raw["params"] == {"status": ["failed"], "date_range": "yesterday"}


def test_registered_action_by_voice() -> None:
    r = req("save the flow", route="/agents/agt_1/flow", actions=[SAVE])
    result, downgraded = validate(keyword_interpret(r), r)
    assert not downgraded and result == {**result, "action": "ui_action", "target": "save_flow"}
