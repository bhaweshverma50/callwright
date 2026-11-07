"""Read-only tool presets for the new-tool dialog (FR-043, T094). Served by
``GET /v1/tools/presets``; creating from a preset is an ordinary ``POST /v1/tools``."""

from __future__ import annotations

from typing import Any

from callwright_contract.http_core import DEFAULT_TIMEOUT_MS
from callwright_contract.values import DEFAULT_EXECUTION_MESSAGE, DEFAULT_HOLD_MESSAGE

PRESETS: tuple[dict[str, Any], ...] = (
    {
        "preset_id": "end_call_polite",
        "type": "end_call",
        "title": "End the call",
        "summary": "Hangs up once the agent has said goodbye and the caller is done.",
        "tool": {
            "type": "end_call",
            "name": "end_call",
            "description": "Hang up once you have said goodbye or the caller is done",
            # Empty: the agent says its own goodbye in the reply that hangs up; a fixed line here
            # would make the caller hear a second goodbye.
            "config": {"message": ""},
        },
    },
    {
        "preset_id": "transfer_to_person",
        "type": "transfer_call",
        "title": "Transfer to a person",
        "summary": "Warm handoff: the agent briefs your colleague privately before connecting.",
        "tool": {
            "type": "transfer_call",
            "name": "transfer_to_person",
            "description": "Transfer the caller to a person when they ask for one or you cannot help",
            "config": {
                "routing_type": "static",
                "transfer_type": "warm",
                "warm_transfer": {
                    "handoff_type": "private",
                    "briefing_message_type": "static",
                    "briefing_message": "I have a caller who would like to speak with someone.",
                },
                "hold_message": DEFAULT_HOLD_MESSAGE,
                "ring_timeout_s": 30,
            },
        },
    },
    {
        "preset_id": "press_digit_ivr",
        "type": "press_digit",
        "title": "Press keypad digits",
        "summary": "Navigates a phone menu by sending keypad tones.",
        "tool": {
            "type": "press_digit",
            "name": "press_digit",
            "description": "Press keypad digits to navigate a phone menu",
            "config": {"delay_ms": 1000, "cooldown_ms": 5000},
        },
    },
    {
        "preset_id": "http_check_availability",
        "type": "http",
        "title": "Check availability",
        "summary": "Calls your booking API with a date and reads back the free slots.",
        "tool": {
            "type": "http",
            "name": "check_availability",
            "description": "Look up free appointment slots for a date",
            "config": {
                "method": "POST",
                "url": "",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Requested date, YYYY-MM-DD"},
                        "doctor_name": {"type": "string", "description": "Doctor the caller asked for"},
                    },
                    "required": ["date"],
                },
                "headers": [{"name": "Content-Type", "value": "application/json", "secret": False}],
                "body_template": None,
                "timeout_ms": DEFAULT_TIMEOUT_MS,
                "response_mappings": [],
                "speak_during_execution": True,
                "execution_message": DEFAULT_EXECUTION_MESSAGE,
            },
        },
    },
)
