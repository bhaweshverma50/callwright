"""Anthropic Messages API adapter (T080). Available to API-side features; not offered as an agent
model at launch (architecture section 7)."""

from __future__ import annotations

from typing import Any

from app.llms.adapters.base import ChatMessage, Completion, ModelError
from app.llms.adapters.openai import post_json

BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"


class AnthropicAdapter:
    name = "anthropic"

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
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if system:
            payload["system"] = system
        body = await post_json(
            f"{BASE_URL}/messages",
            {"x-api-key": self.api_key, "anthropic-version": API_VERSION},
            payload,
            timeout_s,
        )
        try:
            text = "".join(
                str(block.get("text", "")) for block in body["content"] if block.get("type") == "text"
            )
            usage = body.get("usage") or {}
            return Completion(
                text=text,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                provider="anthropic",
                model=model,
                adapter=self.name,
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ModelError("unexpected anthropic response") from exc
