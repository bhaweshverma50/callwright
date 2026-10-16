"""OpenAI Chat Completions adapter (T080)."""

from __future__ import annotations

from typing import Any

import httpx

from app.llms.adapters.base import ChatMessage, Completion, ModelError, ModelTimeout

BASE_URL = "https://api.openai.com/v1"


def chat_payload(
    model: str | None, messages: list[ChatMessage], system: str | None, max_tokens: int, json_mode: bool
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": m.role, "content": m.content} for m in messages],
        "max_completion_tokens": max_tokens,
    }
    if model:
        body["model"] = model
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def parse_chat(body: dict[str, Any], provider: str, model: str, adapter: str) -> Completion:
    try:
        text = body["choices"][0]["message"]["content"] or ""
        usage = body.get("usage") or {}
        return Completion(
            text=str(text),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            provider=provider,
            model=model,
            adapter=adapter,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelError(f"unexpected {provider} response") from exc


async def post_json(
    url: str, headers: dict[str, str], payload: dict[str, Any], timeout_s: float
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ModelTimeout(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ModelError(str(exc)) from exc
    if response.status_code >= 400:
        raise ModelError(f"vendor returned {response.status_code}")
    try:
        data: dict[str, Any] = response.json()
    except ValueError as exc:
        raise ModelError("vendor returned invalid JSON") from exc
    return data


class OpenAIAdapter:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

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
        body = await post_json(
            f"{BASE_URL}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}"},
            chat_payload(model, messages, system, max_tokens, json_mode),
            timeout_s,
        )
        return parse_chat(body, "openai", model, self.name)
