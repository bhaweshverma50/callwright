"""Transcript read model and plain-text copy format (006 T025, FR-009, FR-010)."""

from __future__ import annotations

from app.calls.transcript_text import normalize_items, transcript_text

RAW = [
    {"type": "message", "role": "agent", "text": "Hi, how can I help?", "started_ms": 400, "turn_index": 0},
    {"type": "message", "role": "user", "text": "Check my order", "started_ms": 2100, "confidence": 0.91},
    {"type": "tool_call", "name": "lookup_order", "arguments": {"id": "A12"}, "ref": "t1", "at_ms": 3000},
    {
        "type": "tool_result",
        "name": "lookup_order",
        "output": "shipped",
        "is_error": False,
        "ref": "t1",
        "duration_ms": 420,
    },
    {"type": "flow_transition", "to_node_id": "n2", "from_node_id": "n1", "label": "found"},
    {"type": "tool_call", "name": "refund", "arguments": {}, "at_ms": 5000},
    {"type": "tool_result", "name": "refund", "output": "timeout", "is_error": True, "duration_ms": 3000},
    {
        "type": "message",
        "role": "agent",
        "text": "It shipped yesterday and",
        "interrupted": True,
        "turn_index": 1,
    },
    {"type": "system", "event": "hold"},
]


def test_normalize_keeps_messages_and_tools_only() -> None:
    items = normalize_items(RAW)
    assert [i["type"] for i in items] == [
        "message",
        "message",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "message",
    ]
    assert len({i["id"] for i in items}) == len(items)


def test_normalize_fields() -> None:
    items = normalize_items(RAW)
    agent, user, call, result = items[0], items[1], items[2], items[3]
    assert agent == {
        "id": agent["id"],
        "type": "message",
        "role": "agent",
        "text": "Hi, how can I help?",
        "interrupted": False,
        "stt_confidence": None,
        "offset_ms": 400,
        "turn_index": 0,
    }
    assert user["stt_confidence"] == 0.91 and user["turn_index"] is None
    assert (
        call["tool_name"] == "lookup_order"
        and call["arguments"] == {"id": "A12"}
        and call["offset_ms"] == 3000
    )
    assert result["tool_call_id"] == call["id"]
    assert result["duration_ms"] == 420 and result["is_error"] is False
    # A result without a ref pairs with the latest call of the same tool.
    assert items[5]["tool_call_id"] == items[4]["id"]
    # Offsets never go backwards when the worker omitted one.
    assert items[3]["offset_ms"] >= items[2]["offset_ms"]
    assert items[6]["interrupted"] is True


def test_plain_text_format() -> None:
    text = transcript_text(normalize_items(RAW))
    assert text.splitlines() == [
        "Agent: Hi, how can I help?",
        "Caller: Check my order",
        '[Tool call: lookup_order({"id": "A12"})]',
        "[Tool result: lookup_order -> shipped]",
        "[Tool call: refund({})]",
        "[Tool error: refund -> timeout]",
        "Agent: It shipped yesterday and",
    ]


def test_empty_transcript() -> None:
    assert normalize_items(None) == []
    assert transcript_text([]) == ""
