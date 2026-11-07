"""Inbound webhook reply parsing (010 T061, R13)."""

from __future__ import annotations

import json

import pytest

from app.channels.routing import MAX_REPLY_BYTES, WebhookOutcome, parse_reply, route_detail


def test_full_reply() -> None:
    body = json.dumps(
        {
            "action": "answer",
            "agent_id": "agt_x",
            "dynamic_variables": {"customer_name": "Asha", "n": 3},
            "metadata": {"a": 1},
        }
    ).encode()
    assert parse_reply(body) == {
        "action": "answer",
        "dynamic_variables": {"customer_name": "Asha", "n": "3"},
        "metadata": {"a": 1},
        "agent_id": "agt_x",
    }


def test_empty_body_means_defaults() -> None:
    assert parse_reply(b"") == {} and parse_reply(b"  ") == {}
    assert parse_reply(b"{}")["action"] == "answer"


def test_decline() -> None:
    assert parse_reply(b'{"action":"decline"}')["action"] == "decline"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"x" * (MAX_REPLY_BYTES + 1), "too_large"),
        (b"not json", "invalid_json"),
        (b"[1,2]", "invalid_json"),
        (b'{"action":"hold"}', "invalid_reply"),
        (b'{"dynamic_variables":{"1bad":"x"}}', "invalid_reply"),
        (b'{"dynamic_variables":[]}', "invalid_reply"),
        (b'{"metadata":"x"}', "invalid_reply"),
        (b'{"agent_id":5}', "invalid_reply"),
        (json.dumps({"metadata": {"k": "v" * 5000}}).encode(), "invalid_reply"),
    ],
)
def test_invalid_replies(body: bytes, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_reply(body)


def test_route_detail() -> None:
    assert route_detail(None) is None
    assert route_detail(WebhookOutcome("agt", failure="timeout")) == "inbound_webhook_failed:timeout"
    assert route_detail(WebhookOutcome("agt", declined=True)) == "declined_by_webhook"
    assert route_detail(WebhookOutcome("agt", ignored_agent=True), "route_skipped:unpublished_agent") == (
        "route_skipped:unpublished_agent;inbound_webhook_agent_ignored"
    )
