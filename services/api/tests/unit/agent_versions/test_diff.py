"""Keyed diff (T053, FR-025, research R12)."""

from __future__ import annotations

import copy
from typing import Any

from app.agent_versions.diff import diff_configs
from app.agents.defaults import default_config


def base() -> dict[str, Any]:
    cfg = default_config("single_prompt")
    cfg["prompt"] = "Line one\nLine two"
    cfg["dynamic_variables"] = [
        {"name": "customer_name", "default": "there", "description": None},
        {"name": "order_id", "default": None, "description": None},
    ]
    cfg["advanced"]["pronunciation"] = [{"word": "SQL", "replacement": "sequel"}]
    cfg["tool_ids"] = ["tool_a", "tool_b"]
    return cfg


def test_no_changes() -> None:
    assert diff_configs(base(), base()) == []


def test_scalar_replace() -> None:
    new = base()
    new["prompt"] = "Line one\nLine three"
    new["tts"]["speed"] = 1.2
    assert diff_configs(base(), new) == [
        {"op": "replace", "path": "/prompt", "old": "Line one\nLine two", "new": "Line one\nLine three"},
        {"op": "replace", "path": "/tts/speed", "old": 1.0, "new": 1.2},
    ]


def test_variables_matched_by_name_not_position() -> None:
    new = base()
    new["dynamic_variables"].insert(0, {"name": "account", "default": "x", "description": None})
    new["dynamic_variables"][2]["default"] = "A-1"
    changes = diff_configs(base(), new)
    assert changes == [
        {
            "op": "add",
            "path": "/dynamic_variables[account]",
            "new": {"name": "account", "default": "x", "description": None},
        },
        {"op": "replace", "path": "/dynamic_variables[order_id]/default", "old": None, "new": "A-1"},
    ]


def test_variable_removed() -> None:
    new = base()
    new["dynamic_variables"] = new["dynamic_variables"][:1]
    assert diff_configs(base(), new) == [
        {"op": "remove", "path": "/dynamic_variables[order_id]", "old": base()["dynamic_variables"][1]}
    ]


def test_pronunciation_matched_ignoring_case() -> None:
    new = base()
    new["advanced"]["pronunciation"] = [{"word": "sql", "replacement": "S Q L"}]
    assert diff_configs(base(), new) == [
        {"op": "replace", "path": "/advanced/pronunciation[sql]/word", "old": "SQL", "new": "sql"},
        {
            "op": "replace",
            "path": "/advanced/pronunciation[sql]/replacement",
            "old": "sequel",
            "new": "S Q L",
        },
    ]


def test_tool_ids_by_value() -> None:
    new = base()
    new["tool_ids"] = ["tool_b", "tool_c"]
    assert diff_configs(base(), new) == [
        {"op": "remove", "path": "/tool_ids[tool_a]", "old": "tool_a"},
        {"op": "add", "path": "/tool_ids[tool_c]", "new": "tool_c"},
    ]


def test_snapshot_tools_by_tool_id() -> None:
    old = {**base(), "tools": [{"tool_id": "tool_a", "url": "https://a"}]}
    new = copy.deepcopy(old)
    new["tools"][0]["url"] = "https://b"
    assert diff_configs(old, new) == [
        {"op": "replace", "path": "/tools[tool_a]/url", "old": "https://a", "new": "https://b"}
    ]


def test_block_added_and_removed() -> None:
    new = base()
    new["noise_cancellation"] = None
    new["evals"] = {"x": 1}
    changes = diff_configs(base(), new)
    assert {
        "op": "replace",
        "path": "/noise_cancellation",
        "old": {"provider": "sanas", "model": "vi"},
        "new": None,
    } in changes
    assert {"op": "replace", "path": "/evals", "old": None, "new": {"x": 1}} in changes


def test_stable_document_order() -> None:
    new = base()
    new["kb_ids"] = ["kb_1"]
    new["language"] = "fr"
    new["call_behavior"]["ring_duration_ms"] = 1500
    paths = [c["path"] for c in diff_configs(base(), new)]
    assert paths == ["/language", "/call_behavior/ring_duration_ms", "/kb_ids[kb_1]"]
    assert paths == [c["path"] for c in diff_configs(base(), new)]


def test_numbers_compare_by_value() -> None:
    new = base()
    new["tts"]["speed"] = 1
    assert diff_configs(base(), new) == []
