"""Voice command benchmark (006 T074, SC-007): 60 utterances through the deterministic interpreter
and the server validation. At least 85% must give the intended outcome and none may run an action
the page did not register."""

from __future__ import annotations

from typing import Any

from app.voice_commands.interpreter import keyword_interpret, validate
from app.voice_commands.schemas import InterpretRequest

PAGE_ACTIONS = {
    "/dashboard": [
        {"key": "refresh_dashboard", "label": "Refresh the dashboard"},
        {"key": "ask_analytics", "label": "Ask analytics"},
    ],
    "/calls": [
        {"key": "filter_calls", "label": "Filter calls"},
        {"key": "export_calls", "label": "Export calls"},
    ],
    "/agents/agt_1/flow": [
        {"key": "save_flow", "label": "Save the flow"},
        {"key": "publish_flow", "label": "Publish the flow"},
    ],
}

# (route, transcript, expected action, expected target or None)
CASES: list[tuple[str, str, str, str | None]] = [
    *[
        ("/dashboard", t, "navigate", "/calls")
        for t in (
            "show me failed calls from yesterday",
            "show failed calls from today",
            "show me completed calls",
            "list whatsapp calls from this week",
            "find inbound calls from yesterday",
            "show me busy calls",
            "show calls from the last 7 days",
            "filter calls that failed",
            "show me no answer calls",
            "show web calls from today",
        )
    ],
    *[
        ("/calls", f"go to {p}", "navigate", r)
        for p, r in (
            ("billing", "/billing"),
            ("the dashboard", "/dashboard"),
            ("agents", "/agents"),
            ("settings", "/settings"),
            ("simulations", "/simulations"),
            ("datasets", "/datasets"),
            ("issues", "/issues"),
            ("review", "/review"),
            ("calibration", "/calibration"),
            ("knowledge", "/knowledge-base"),
            ("phone numbers", "/phone-numbers"),
            ("templates", "/agents/templates"),
        )
    ],
    *[
        ("/dashboard", f"open the {p} page", "navigate", r)
        for p, r in (("billing", "/billing"), ("agents", "/agents"), ("calls", "/calls"))
    ],
    *[
        ("/dashboard", t, "route_to_copilot", "analytics_chat")
        for t in (
            "open the analytics assistant and ask what our busiest day was",
            "ask how many calls we had yesterday",
            "open the assistant and ask cost by agent this month",
            "ask what the average call duration was last week",
            "open analytics and ask which agent is slowest",
        )
    ],
    ("/dashboard", "refresh the dashboard", "ui_action", "refresh_dashboard"),
    ("/agents/agt_1/flow", "save the flow", "ui_action", "save_flow"),
    ("/agents/agt_1/flow", "please save the flow now", "ui_action", "save_flow"),
    ("/agents/agt_1/flow", "publish the flow", "ui_action", "publish_flow"),
    ("/calls", "export calls", "ui_action", "export_calls"),
    *[(r, "what page am I on", "answer", None) for r in ("/dashboard", "/calls", "/agents/agt_1/flow")],
    ("/dashboard", "where am i", "answer", None),
    *[
        ("/dashboard", t, "decline", None)
        for t in (
            "delete this agent",
            "delete all calls",
            "remove the agent",
            "save the flow",
            "publish the flow",
            "drop the database",
            "sing me a song",
            "what's the weather",
            "erase my account",
            "order a pizza",
            "make me an admin",
            "transfer money to my account",
            "turn off the lights",
            "book a flight",
            "tell me a joke",
            "export calls",
            "open the pod bay doors",
            "hack the mainframe",
            "cancel my subscription forever",
            "what is the meaning of life",
            "print every password",
        )
    ],
]


def _req(route: str, transcript: str) -> InterpretRequest:
    return InterpretRequest.model_validate(
        {
            "transcript": transcript,
            "visual_state": {
                "current_route": route,
                "page_title": None,
                "current_datetime": "2026-10-16T10:00:00Z",
                "timezone": "UTC",
                "available_actions": PAGE_ACTIONS.get(route, []),
            },
        }
    )


def test_benchmark_has_sixty_utterances() -> None:
    assert len(CASES) == 60


def test_intended_outcomes_and_no_unregistered_actions() -> None:
    hits = 0
    misses: list[Any] = []
    for route, transcript, action, target in CASES:
        req = _req(route, transcript)
        result, _ = validate(keyword_interpret(req), req)
        if result["action"] == "ui_action":
            assert result["target"] in {a["key"] for a in PAGE_ACTIONS.get(route, [])}
        if result["action"] == action and (target is None or result["target"] == target):
            hits += 1
        else:
            misses.append((transcript, result["action"], result["target"]))
    assert hits / len(CASES) >= 0.85, misses
