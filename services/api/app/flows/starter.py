"""Node defaults and the starter graph of a new flow agent (T016, FR-003, FR-004).

The defaults table matches the spec's Node Types table; the web palette keeps the same values.
"""

from __future__ import annotations

import copy
import secrets
from typing import Any

from app.tools.schemas import DEFAULT_EXECUTION_MESSAGE, DEFAULT_HOLD_MESSAGE

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
DEFAULT_GREETING = "Hi, thanks for calling. How can I help?"
DEFAULT_END_MESSAGE = "Thanks for calling. Goodbye."


def short_id(prefix: str) -> str:
    return f"{prefix}_" + "".join(secrets.choice(ALPHABET) for _ in range(8))


def empty_overrides() -> dict[str, Any]:
    return {"llm": None, "tts": None, "stt": None, "language": None}


DEFAULT_LABELS: dict[str, str] = {
    "start": "Start",
    "agent": "Agent",
    "task": "Collect details",
    "condition": "Route",
    "say": "Say",
    "extract_variable": "Extract",
    "webhook": "API call",
    "transfer": "Transfer",
    "end": "End",
}

_DEFAULTS: dict[str, dict[str, Any]] = {
    "start": {"start_speaker": "agent", "greeting_type": "static", "greeting": DEFAULT_GREETING},
    "agent": {
        "instructions": "",
        "begin_message": None,
        "context_strategy": "inherit",
        "overrides": empty_overrides(),
        "tool_ids": [],
        "kb_search_enabled": True,
    },
    "task": {
        "instructions": "",
        "fields": [
            {"name": "name", "type": "string", "description": "The caller's full name", "required": True},
            {
                "name": "email",
                "type": "string",
                "description": "The caller's email address",
                "required": True,
            },
        ],
        "max_rounds": 5,
        "context_strategy": "inherit",
        "overrides": empty_overrides(),
        "tool_ids": [],
        "kb_search_enabled": True,
    },
    "condition": {
        "kind": "classify",
        "instructions": "",
        "categories": [
            {"name": "Sales", "description": "The caller wants to buy something or asks about prices"},
            {"name": "Support", "description": "The caller needs help with something they already have"},
        ],
    },
    "say": {"message": "", "allow_interruptions": True},
    "extract_variable": {"instructions": "", "fields": []},
    "webhook": {
        "request": {
            "method": "POST",
            "url": "",
            "headers": [{"name": "Content-Type", "value": "application/json", "secret": False}],
            "body_template": None,
            "timeout_ms": 8000,
            "response_mappings": [],
            "speak_during_execution": True,
            "execution_message": DEFAULT_EXECUTION_MESSAGE,
        },
        "mock_response": None,
    },
    "transfer": {
        "transfer": {
            "routing_type": "static",
            "number": None,
            "routing_instructions": None,
            "allowed_numbers": [],
            "transfer_type": "cold",
            "warm_transfer": None,
            "hold_message": DEFAULT_HOLD_MESSAGE,
            "ring_timeout_s": 30,
        }
    },
    "end": {"message": DEFAULT_END_MESSAGE, "reason": "call_completed"},
}


def node_defaults(node_type: str) -> dict[str, Any]:
    return copy.deepcopy(_DEFAULTS[node_type])


def config_with_defaults(node_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """``config`` over the type's defaults (missing keys filled, nothing else touched)."""
    base = node_defaults(node_type) if node_type in _DEFAULTS else {}
    base.update(copy.deepcopy(config or {}))
    return base


def starter_graph() -> dict[str, Any]:
    """Start -> Agent "Conversation" -> End, connected; validates with no errors (SC-001)."""
    start, agent, end = short_id("n"), short_id("n"), short_id("n")
    agent_config = node_defaults("agent")
    agent_config["instructions"] = (
        "Find out why the caller is calling and help them with their request. Ask one question at "
        "a time and confirm important details."
    )
    return {
        "nodes": [
            {
                "id": start,
                "type": "start",
                "label": "Start",
                "position": {"x": 0, "y": 0},
                "config": node_defaults("start"),
            },
            {
                "id": agent,
                "type": "agent",
                "label": "Conversation",
                "position": {"x": 360, "y": 0},
                "config": agent_config,
            },
            {
                "id": end,
                "type": "end",
                "label": "End",
                "position": {"x": 720, "y": 0},
                "config": node_defaults("end"),
            },
        ],
        "edges": [
            {"id": short_id("e"), "source": start, "target": agent, "trigger": "always", "sort_order": 0},
            {
                "id": short_id("e"),
                "source": agent,
                "target": end,
                "trigger": "llm_condition",
                "label": "Caller is done",
                "condition": "The caller has nothing else to ask and is ready to end the call",
                "sort_order": 0,
            },
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
