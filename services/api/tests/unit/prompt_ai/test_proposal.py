"""Proposal extraction (T078)."""

from __future__ import annotations

import json

from app.prompt_ai.proposal import parse_answer


def test_reply_only() -> None:
    reply, proposal = parse_answer(json.dumps({"reply": "What business is it for?", "proposal": None}))
    assert reply == "What business is it for?" and proposal is None


def test_reply_with_proposal_in_code_fence() -> None:
    text = (
        "```json\n"
        + json.dumps(
            {
                "reply": "Here you go.",
                "proposal": {
                    "prompt": "You book dental visits for {{clinic}}.",
                    "begin_message": "Hi, {{clinic}} here.",
                    "dynamic_variables": ["clinic"],
                },
            }
        )
        + "\n```"
    )
    reply, proposal = parse_answer(text)
    assert reply == "Here you go."
    assert proposal == {
        "prompt": "You book dental visits for {{clinic}}.",
        "begin_message": "Hi, {{clinic}} here.",
        "dynamic_variables": ["clinic"],
    }


def test_plain_text_is_a_reply() -> None:
    assert parse_answer("Sure, tell me more.") == ("Sure, tell me more.", None)


def test_malformed_proposal_ignored() -> None:
    for bad in ({"prompt": ""}, {"prompt": 5}, "a string", {"greeting": "x"}):
        reply, proposal = parse_answer(json.dumps({"reply": "Hm.", "proposal": bad}))
        assert reply == "Hm." and proposal is None


def test_invalid_and_reserved_variable_names_dropped_and_missing_ones_extracted() -> None:
    _, proposal = parse_answer(
        json.dumps(
            {
                "reply": "ok",
                "proposal": {
                    "prompt": "Hi {{customer}}, order {{order_id}} at {{current_time}}.",
                    "dynamic_variables": ["customer", "bad name", "call_id", "9x", {"name": "plan"}],
                },
            }
        )
    )
    assert proposal is not None
    assert proposal["dynamic_variables"] == ["customer", "plan", "order_id"]
    assert proposal["begin_message"] is None


def test_missing_reply_text_gets_a_default() -> None:
    reply, proposal = parse_answer(json.dumps({"proposal": {"prompt": "x"}}))
    assert proposal is not None and reply
