"""Small values both services use: phone number and keypad syntax, tool names, error codes and
default texts, callback limits and wording (011), stock lines and the text runner's queue (008)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Final, Literal

E164_PATTERN: Final = r"^\+[1-9]\d{6,14}$"
E164 = re.compile(E164_PATTERN)

KEYPAD_DIGITS: Final = frozenset("0123456789*#")
# Digits one press_digit call may send (005), and digits one dtmf event may carry.
MAX_PRESS_DIGITS: Final = 20
PRESS_DIGITS_PATTERN: Final = rf"^[0-9*#]{{1,{MAX_PRESS_DIGITS}}}$"
DTMF_EVENT_DIGITS_PATTERN: Final = r"^[0-9*#]{1,99}$"

# Tools every agent has without configuring them; tool names the builder may not use.
END_CALL_TOOL: Final = "end_call"
SCHEDULE_CALLBACK_TOOL: Final = "schedule_callback"
SET_LANGUAGE_TOOL: Final = "set_language"
KB_TOOL: Final = "kb_search"
COMPLETE_TASK_TOOL: Final = "complete_task"
ROUTE_TOOL_PREFIX: Final = "route_to_"

# Codes a tool result carries in ``{"error": code, "message": ...}`` (005 data-model ToolCall).
ToolErrorCode = Literal[
    "invalid_arguments",
    "missing_variable",
    "secret_unavailable",
    "blocked_address",
    "connection_error",
    "timeout",
    "http_status",
    "response_too_large",
    "channel_unsupported",
    "transfer_failed",
    "no_mock_response",
    "invalid_time",
    "unavailable",
]
CHANNEL_UNSUPPORTED: Final = "channel_unsupported"

DEFAULT_HOLD_MESSAGE: Final = "Please hold while I connect you."
DEFAULT_EXECUTION_MESSAGE: Final = "One moment while I check that."
# The goodbye an End node (004) says when the builder wrote none: the flow starter used to store
# it, and the worker treats it as "no fixed line" and writes one for the call.
STOCK_GOODBYE: Final = "Thanks for calling. Goodbye."

# 011 callbacks booked from a call.
CALLBACK_MAX_NOTE_CHARS: Final = 500
CALLBACK_MAX_IN_MINUTES: Final = 30 * 24 * 60
CALLBACK_NOT_A_PHONE_CALL: Final = (
    "Callbacks can only be booked on phone calls. Tell the caller you cannot book a callback on this call."
)


def spoken_time(local: datetime, now_local: datetime) -> str:
    """``today at 5:00 pm``, ``tomorrow, Wednesday 4 November, at 5:00 pm`` or
    ``Friday 6 November at 9:30 am`` (both in the recipient's zone)."""
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"
    day = f"{local.strftime('%A')} {local.day} {local.strftime('%B')}"
    if local.date() == now_local.date():
        return f"today at {clock}"
    if local.date() == now_local.date() + timedelta(days=1):
        return f"tomorrow, {day}, at {clock}"
    return f"{day} at {clock}"


# 008 text runner: the arq queue the voice worker's ``textsim`` role consumes, its two jobs and
# why a simulated conversation ended.
TEXTSIM_QUEUE: Final = "arq:textsim"
RUN_SINGLE_TURN: Final = "run_single_turn"
RUN_SIMULATION: Final = "run_simulation"
SimulationEndReason = Literal[
    "caller_turns_exhausted",
    "caller_hung_up",
    "agent_hangup",
    "call_transfer",
    "turn_limit_reached",
    "error",
]
