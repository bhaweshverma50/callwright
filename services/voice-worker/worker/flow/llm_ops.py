"""Silent model calls of a flow: classify, extract and the background summary (T060, T062,
T079). They use the call's default LLM component through the LiveKit ``llm.LLM`` interface, so
no vendor is named here (Principle I). Structured output is a single forced function call whose
parameters are the wanted schema; the arguments are the answer.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from worker.flow.context import Message

CLASSIFY_TIMEOUT_S = 1.5
EXTRACT_TIMEOUT_S = 8.0
SUMMARY_TIMEOUT_S = 10.0
GOODBYE_MAX_CHARS = 300
GOODBYE_SYSTEM = (
    "You are the voice agent on this phone call, and the call is ending now. Write only what you "
    "say as you hang up: one or two short spoken sentences that fit this conversation. If a "
    "callback or next step was agreed and you have not confirmed it yet, confirm it briefly (with "
    "the time if one was given); never repeat what you just said and never promise anything that "
    "was not agreed. Then say goodbye. Speak in the language of the conversation. Plain words "
    "only: no quotes, lists, markdown or emojis."
)
CLASSIFY_TOOL = "choose_category"
EXTRACT_TOOL = "save_values"


def raw_tool(name: str, description: str, parameters: Mapping[str, Any], fn: Any = None) -> Any:
    """A LiveKit function tool from a JSON schema; ``fn(arguments, context)`` runs it."""
    from livekit.agents import RunContext, function_tool

    async def handler(raw_arguments: dict[str, object], context: RunContext) -> Any:  # type: ignore[type-arg]
        return await fn(dict(raw_arguments), context) if fn is not None else ""

    handler.__annotations__ = {"raw_arguments": dict, "context": RunContext, "return": Any}
    schema = {"name": name, "description": description, "parameters": dict(parameters)}
    return function_tool(handler, raw_schema=schema)


def transcript(history: Sequence[Message], limit: int = 40) -> str:
    lines = [
        f"{'Caller' if role == 'user' else 'Agent'}: {text}"
        for role, text in history[-limit:]
        if text
    ]
    return "\n".join(lines) or "(no conversation yet)"


async def _forced_call(
    llm: Any,
    system: str,
    user: str,
    name: str,
    description: str,
    parameters: Mapping[str, Any],
    timeout_s: float,
) -> dict[str, Any] | None:
    from livekit.agents import llm as lk_llm

    ctx = lk_llm.ChatContext.empty()
    ctx.add_message(role="system", content=system)
    ctx.add_message(role="user", content=user)

    tool = raw_tool(name, description, parameters)

    async def run() -> dict[str, Any] | None:
        stream = llm.chat(chat_ctx=ctx, tools=[tool], tool_choice="required")
        args = ""
        async with stream:
            async for chunk in stream:
                delta = getattr(chunk, "delta", None)
                for call in getattr(delta, "tool_calls", None) or []:
                    if call.name == name:
                        args += call.arguments or ""
        if not args:
            return None
        try:
            value = json.loads(args)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    try:
        return await asyncio.wait_for(run(), timeout=timeout_s)
    except (TimeoutError, Exception):
        return None


async def classify(
    llm: Any, history: Sequence[Message], instructions: str, categories: Sequence[Mapping[str, Any]]
) -> str | None:
    names = [str(c.get("name")) for c in categories]
    lines = "\n".join(
        f"- {c.get('name')}: {c.get('description') or ''}".rstrip(": ") for c in categories
    )
    system = (
        "You route a phone call. Read the conversation and choose exactly one category.\n"
        f"{instructions.strip()}\n\nCategories:\n{lines}"
    ).strip()
    params = {
        "type": "object",
        "properties": {"category": {"type": "string", "enum": names}},
        "required": ["category"],
        "additionalProperties": False,
    }
    result = await _forced_call(
        llm,
        system,
        transcript(history),
        CLASSIFY_TOOL,
        "Choose the category.",
        params,
        CLASSIFY_TIMEOUT_S,
    )
    choice = (result or {}).get("category")
    return str(choice) if isinstance(choice, str) and choice in names else None


async def extract(
    llm: Any, history: Sequence[Message], instructions: str, schema: Mapping[str, Any]
) -> dict[str, Any]:
    system = (
        "Extract values from the phone conversation. Leave out anything the caller did not say.\n"
        f"{instructions.strip()}"
    ).strip()
    params = {**dict(schema), "required": []}
    result = await _forced_call(
        llm,
        system,
        transcript(history),
        EXTRACT_TOOL,
        "Save the extracted values.",
        params,
        EXTRACT_TIMEOUT_S,
    )
    return result or {}


async def summarize(llm: Any, history: Sequence[Message], previous: str | None) -> str:
    from livekit.agents import llm as lk_llm

    ctx = lk_llm.ChatContext.empty()
    ctx.add_message(
        role="system",
        content="Summarise this phone call so far in at most three short sentences: who the "
        "caller is, what they want and what has been agreed. Plain text.",
    )
    body = transcript(history)
    if previous:
        body = f"Earlier summary: {previous}\n\n{body}"
    ctx.add_message(role="user", content=body)

    async def run() -> str:
        stream = llm.chat(chat_ctx=ctx)
        text = ""
        async with stream:
            async for chunk in stream:
                delta = getattr(chunk, "delta", None)
                text += getattr(delta, "content", None) or ""
        return text[:1200]

    return await asyncio.wait_for(run(), timeout=SUMMARY_TIMEOUT_S)


async def goodbye(
    llm: Any,
    history: Sequence[Message],
    reply_language: str | None = None,
    *,
    booked: str | None = None,
) -> str:
    """The goodbye of an End node without a line of its own (no timeout here: the runtime
    bounds the wait and falls back to the stock line). ``booked``: the spoken time of a
    callback booked on this call."""
    from livekit.agents import llm as lk_llm

    system = GOODBYE_SYSTEM
    if booked:
        system += f" A callback was booked on this call for {booked}."
    if reply_language:
        system += f" Reply only in {reply_language}."
    ctx = lk_llm.ChatContext.empty()
    ctx.add_message(role="system", content=system)
    ctx.add_message(role="user", content=transcript(history, limit=20))
    stream = llm.chat(chat_ctx=ctx)
    text = ""
    async with stream:
        async for chunk in stream:
            delta = getattr(chunk, "delta", None)
            text += getattr(delta, "content", None) or ""
    return " ".join(text.split()).strip().strip('"').strip()[:GOODBYE_MAX_CHARS]
