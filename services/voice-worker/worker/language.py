"""Caller language (012): the reply-language instruction, the set_language rule and the greeting
in the caller's saved language.

The API sends ``RuntimeConfig.language_options`` (the agent's language first, then every
language its speech recognition provider and voice can both handle, with the models to use)
and, on phone calls, ``caller_language`` (the caller's saved language). The worker starts the
call in that language: speech recognition and voice for it, the reply-language line in the
instructions and a greeting with the same meaning as the agent's fixed greeting.

Greeting: the fixed greeting is written in the agent's language, so it is translated once at
call start with the agent's own model (a separate client, so the session's metrics do not see
it) while the session starts and the phone rings, then synthesised like any fixed greeting.
That keeps the greeting pre-synthesised (no added wait when the caller answers in the usual
case). If the translation is not back within ``GREETING_TRANSLATION_TIMEOUT_S`` or fails, the
model writes the opening live instead (``translated_greeting_instruction``), which costs about
one model reply of latency but never leaves the caller in silence.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

GREETING_TRANSLATION_TIMEOUT_S = 4.0
REPLY_LANGUAGE_PREFIX = "Language rule:"
_REPLY_LINE = re.compile(r"\n*Language rule:[^\n]*")


def reply_language_instruction(label: str) -> str:
    return (
        f"{REPLY_LANGUAGE_PREFIX} reply only in {label} from now on, even when earlier messages "
        f"are in another language, until the caller asks for a different language."
    )


def with_reply_language(instructions: str, label: str | None) -> str:
    """``instructions`` with its reply-language line replaced (removed when ``label`` is None)."""
    base = _REPLY_LINE.sub("", instructions).rstrip()
    if not label:
        return base
    return (
        f"{base}\n\n{reply_language_instruction(label)}"
        if base
        else reply_language_instruction(label)
    )


def set_language_instruction(options: Sequence[Any]) -> str:
    """When to call set_language (single-prompt agents and every flow node, when the claim offers
    something to switch to)."""
    names = ", ".join(f"{_get(o, 'label')} ({_get(o, 'code')})" for o in options)
    return (
        "Callers may prefer another language. If the caller asks to speak in another language, or "
        "clearly speaks one for a full sentence, call set_language with its code before replying, "
        "then confirm the switch in that language in one short sentence and carry on in it. Do not "
        "switch for a single foreign word or a name, and do not switch on your own initiative. "
        f"Languages you can switch to: {names}. If the caller asks for a language that is not "
        "listed, say politely in the current language that you cannot speak it."
    )


def translated_greeting_instruction(greeting: str, label: str) -> str:
    return (
        f"Open the call in {label} with a greeting that means the same as this one, keeping any "
        f"names and disclosures, and nothing else: {greeting}"
    )


def _get(option: Any, key: str) -> Any:
    return option.get(key) if isinstance(option, Mapping) else getattr(option, key, None)


TokenUsage = Callable[[int, int], None]


async def translate_greeting(
    llm: Any,
    greeting: str,
    label: str,
    *,
    on_usage: TokenUsage | None = None,
    timeout_s: float = GREETING_TRANSLATION_TIMEOUT_S,
) -> str:
    """The greeting in ``label``, written by ``llm`` (a LiveKit LLM). Raises on failure or
    timeout."""
    from livekit.agents import llm as lk_llm

    ctx = lk_llm.ChatContext.empty()
    ctx.add_message(
        role="system",
        content=(
            f"Translate the phone greeting the user sends into {label}. Keep names, numbers and "
            "any disclosure; keep it natural and spoken, as short as the original. Reply with the "
            "translation only, no quotes or notes."
        ),
    )
    ctx.add_message(role="user", content=greeting)

    async def run() -> str:
        parts: list[str] = []
        async with llm.chat(chat_ctx=ctx) as stream:
            async for chunk in stream:
                delta = getattr(chunk, "delta", None)
                if delta is not None and getattr(delta, "content", None):
                    parts.append(str(delta.content))
                usage = getattr(chunk, "usage", None)
                if usage is not None and on_usage is not None:
                    on_usage(
                        int(getattr(usage, "prompt_tokens", 0) or 0),
                        int(getattr(usage, "completion_tokens", 0) or 0),
                    )
        return "".join(parts).strip().strip('"').strip()

    text = await asyncio.wait_for(run(), timeout_s)
    if not text:
        raise ValueError("empty translation")
    return text
