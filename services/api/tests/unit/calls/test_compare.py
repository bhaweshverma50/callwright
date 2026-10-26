"""Turn alignment and flow diff for the compare page (006 T053, FR-016)."""

from __future__ import annotations

from typing import Any

from app.calls.compare import align_turns, flow_diff


def _msg(item_id: str, role: str) -> dict[str, Any]:
    return {"id": item_id, "type": "message", "role": role}


def _tool(item_id: str) -> dict[str, Any]:
    return {"id": item_id, "type": "tool_call"}


def test_turns_start_at_each_caller_message() -> None:
    left = [
        _msg("a0", "agent"),
        _msg("u1", "user"),
        _tool("t1"),
        _msg("a1", "agent"),
        _msg("u2", "user"),
        _msg("a2", "agent"),
    ]
    right = [_msg("b0", "agent"), _msg("v1", "user"), _msg("b1", "agent")]
    assert align_turns(left, right) == [
        {"turn_index": 0, "left_item_ids": ["a0"], "right_item_ids": ["b0"]},
        {"turn_index": 1, "left_item_ids": ["u1", "t1", "a1"], "right_item_ids": ["v1", "b1"]},
        {"turn_index": 2, "left_item_ids": ["u2", "a2"], "right_item_ids": []},
    ]


def test_caller_speaks_first() -> None:
    left = [_msg("u1", "user"), _msg("a1", "agent")]
    assert align_turns(left, []) == [{"turn_index": 1, "left_item_ids": ["u1", "a1"], "right_item_ids": []}]


def test_empty_calls_align_to_nothing() -> None:
    assert align_turns([], []) == []


def _hop(to: str, frm: str | None = None) -> dict[str, Any]:
    return {"to_node_id": to, "from_node_id": frm}


def test_flow_diff_marks_differing_nodes() -> None:
    left = [_hop("greet"), _hop("verify", "greet"), _hop("refund", "verify")]
    right = [_hop("greet"), _hop("verify", "greet"), _hop("escalate", "verify"), _hop("end", "escalate")]
    assert flow_diff(left, right) == [
        {"sequence": 1, "left_node_id": "greet", "right_node_id": "greet", "differs": False},
        {"sequence": 2, "left_node_id": "verify", "right_node_id": "verify", "differs": False},
        {"sequence": 3, "left_node_id": "refund", "right_node_id": "escalate", "differs": True},
        {"sequence": 4, "left_node_id": None, "right_node_id": "end", "differs": True},
    ]


def test_flow_diff_single_prompt_calls() -> None:
    assert flow_diff([], []) == []
