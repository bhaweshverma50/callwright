"""Parse the assistant's answer into a reply and an optional proposal (T078).

The model is asked for ``{"reply": ..., "proposal": null | {...}}``. Anything else is treated
as a plain reply without a proposal. A proposal needs a non-empty ``prompt``; invalid or
built-in variable names are dropped, and when the model lists none, the names are taken from
the proposed prompt and greeting.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents import variables
from app.agents.schemas import MAX_GREETING, MAX_PROMPT

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1) if match else stripped


def _clean_proposal(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        return None
    greeting = raw.get("begin_message")
    if not isinstance(greeting, str) or not greeting.strip() or len(greeting) > MAX_GREETING:
        greeting = None
    names_raw = raw.get("dynamic_variables")
    names: list[str] = []
    if isinstance(names_raw, list):
        for item in names_raw:
            name = item.get("name") if isinstance(item, dict) else item
            if (
                isinstance(name, str)
                and variables.is_valid_name(name)
                and not variables.is_reserved(name)
                and name not in names
            ):
                names.append(name)
    for name in variables.usable_names([prompt, greeting]):
        if name not in names:
            names.append(name)
    return {"prompt": prompt.strip(), "begin_message": greeting, "dynamic_variables": names[:50]}


def parse_answer(text: str) -> tuple[str, dict[str, Any] | None]:
    body = _strip_fence(text)
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return (text.strip() or "I could not draft a proposal this time. Please try again."), None
    if not isinstance(data, dict):
        return text.strip(), None
    reply = data.get("reply")
    proposal = _clean_proposal(data.get("proposal"))
    if not isinstance(reply, str) or not reply.strip():
        reply = (
            "Here is a proposal." if proposal else "Could you tell me more about what the agent should do?"
        )
    return reply.strip(), proposal
