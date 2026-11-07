"""Dynamic variables: built-in names, the name rule, limits and the ``{{name}}`` grammar
(002 FR-008, 003 FR-005, 004 research R6).

Built-ins are set by the API at admission for every call (``app.calls.variables.builtin_values``)
and may appear in any text but cannot be declared. Placeholders tolerate spaces inside the braces;
flow text also reads one level of dotted name for task results (``{{task_result.email}}``). HTTP
tool templates use their own wider grammar (``http_core.PLACEHOLDER``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

BUILTIN_VARIABLES: Final[tuple[str, ...]] = (
    "call_id",
    "channel",
    "direction",
    "user_number",
    "agent_number",
    "timezone",
    "current_time",
    "current_date",
    "current_datetime",
)
# Set on a callback call (011): why the agent is calling back.
CALLBACK_NOTE: Final = "callback_note"

_NAME = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
NAME_PATTERN: Final = rf"^{_NAME}$"
NAME = re.compile(NAME_PATTERN)
PLACEHOLDER = re.compile(rf"\{{\{{\s*({_NAME})\s*\}}\}}")
DOTTED_PLACEHOLDER = re.compile(rf"\{{\{{\s*({_NAME}(?:\.{_NAME})?)\s*\}}\}}")

MAX_VARIABLES: Final = 50
MAX_VALUE_CHARS: Final = 2000
MAX_DESCRIPTION_CHARS: Final = 200


def render(text: str, variables: Mapping[str, str]) -> str:
    """Replace ``{{name}}`` placeholders; a name with no value renders empty, never raw."""
    return PLACEHOLDER.sub(lambda m: str(variables.get(m.group(1), "")), text)
