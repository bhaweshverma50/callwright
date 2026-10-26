"""Deterministic fake model adapter (T080): dev without vendor keys, and every test.

Token counts are estimated (four characters per token) so feature charges are realistic. For
``purpose="prompt_assistant"`` it answers in the assistant's JSON format, drafting a prompt from
the request or tightening the current prompt (read from the ``<current_prompt>`` block of the
system message). Test markers in the last user message: ``[timeout]`` raises ``ModelTimeout``,
``[error]`` raises ``ModelError``, ``[malformed]`` returns text that is not JSON, and
``[no proposal]`` returns a reply without a proposal.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from app.llms.adapters.base import ChatMessage, Completion, ModelError, ModelTimeout, estimate_tokens

_CURRENT = re.compile(r"<current_prompt>\n?(.*?)\n?</current_prompt>", re.DOTALL)


def _current_prompt(system: str | None) -> str:
    if not system:
        return ""
    match = _CURRENT.search(system)
    return match.group(1).strip() if match else ""


def _concise(prompt: str) -> str:
    lines = [line.rstrip() for line in prompt.splitlines() if line.strip()]
    kept = [line for line in lines if not line.lstrip().startswith(("-", "*")) or len(line) < 90]
    return "\n".join(kept[: max(3, len(kept) // 2 + 1)])


def _draft(request: str) -> str:
    goal = request.strip().rstrip(".")
    return (
        "You are a friendly voice agent for {{company_name}}.\n\n"
        f"## Purpose\n{goal[:1].upper() + goal[1:]}.\n\n"
        "## How to handle the call\n"
        "- Greet the caller and find out why they are calling.\n"
        "- Ask one question at a time and confirm important details by repeating them.\n"
        "- If you cannot help, offer to pass the request to the team and take a callback number.\n\n"
        "## Style\n"
        "- Speak in short, warm sentences.\n"
        "- Never invent prices, policies or availability you were not given."
    )


def assistant_reply(messages: list[ChatMessage], system: str | None) -> str:
    last = next((m.content for m in reversed(messages) if m.role == "user"), "")
    lowered = last.lower()
    if "[malformed]" in lowered:
        return "{this is not json"
    if "[no proposal]" in lowered:
        return json.dumps(
            {"reply": "Tell me who the agent talks to and what it should achieve.", "proposal": None}
        )
    current = _current_prompt(system)
    if current and any(word in lowered for word in ("concise", "shorter", "shorten", "tighten")):
        return json.dumps(
            {
                "reply": "Here is a more concise version of your prompt.",
                "proposal": {"prompt": _concise(current), "begin_message": None, "dynamic_variables": []},
            }
        )
    return json.dumps(
        {
            "reply": "Here is a first draft. Adjust the purpose and details to match your business.",
            "proposal": {
                "prompt": _draft(last),
                "begin_message": "Thanks for calling {{company_name}}. How can I help you today?",
                "dynamic_variables": ["company_name"],
            },
        }
    )


# Deterministic replies other features register for their own ``purpose`` (004 flow assistant).
PURPOSE_REPLIES: dict[str, Callable[[list[ChatMessage], str | None], str]] = {}


class FakeAdapter:
    name = "fake"

    def __init__(self, provider: str = "fake") -> None:
        self.provider = provider

    async def complete(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        system: str | None,
        max_tokens: int,
        timeout_s: float,
        json_mode: bool,
        purpose: str | None,
    ) -> Completion:
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "[timeout]" in last.lower():
            raise ModelTimeout("fake timeout")
        if "[error]" in last.lower():
            raise ModelError("fake error")
        if purpose == "prompt_assistant":
            text = assistant_reply(messages, system)
        elif purpose in PURPOSE_REPLIES:
            text = PURPOSE_REPLIES[purpose](messages, system)
        else:
            text = json.dumps({"reply": f"(fake) {last[:200]}"}) if json_mode else f"(fake) {last[:200]}"
        prompt_text = (system or "") + "".join(m.content for m in messages)
        return Completion(
            text=text,
            input_tokens=estimate_tokens(prompt_text),
            output_tokens=estimate_tokens(text),
            provider=self.provider,
            model=model,
            adapter=self.name,
        )
