"""Allowed and recommended fix kinds (009 T025; spec FR-008)."""

from __future__ import annotations

import pytest

from app.issues.kinds import allowed_kinds, is_allowed, recommended_kind


def test_single_prompt_agent() -> None:
    assert allowed_kinds("single_prompt", None) == [
        "prompt_edit",
        "add_guardrail",
        "tool_description_edit",
        "kb_attach",
    ]
    assert recommended_kind("single_prompt", None) == "prompt_edit"
    # A node on a single-prompt issue changes nothing.
    assert allowed_kinds("single_prompt", "n_whatever") == allowed_kinds("single_prompt", None)


def test_node_attributed_flow_issue() -> None:
    kinds = allowed_kinds("flow", "n_collect1")
    assert kinds[0] == "node_prompt_edit"
    assert set(kinds) == {
        "node_prompt_edit",
        "add_guardrail",
        "transition_condition_edit",
        "add_transition",
        "node_tool_attachment",
        "tool_description_edit",
        "kb_attach",
    }
    assert recommended_kind("flow", "n_collect1") == "node_prompt_edit"


def test_flow_issue_without_node() -> None:
    assert allowed_kinds("flow", None) == ["add_guardrail", "tool_description_edit", "kb_attach"]
    assert recommended_kind("flow", None) == "add_guardrail"


@pytest.mark.parametrize(
    ("agent_type", "node", "kind", "ok"),
    [
        ("single_prompt", None, "node_prompt_edit", False),
        ("single_prompt", None, "prompt_edit", True),
        ("flow", None, "prompt_edit", False),
        ("flow", None, "node_prompt_edit", False),
        ("flow", "n_a", "add_transition", True),
        ("flow", "n_a", "prompt_edit", False),
        ("flow", "n_a", "made_up", False),
    ],
)
def test_is_allowed(agent_type: str, node: str | None, kind: str, ok: bool) -> None:
    assert is_allowed(agent_type, node, kind) is ok
