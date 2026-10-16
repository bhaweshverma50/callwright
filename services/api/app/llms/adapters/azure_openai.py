"""Azure OpenAI adapter (T080). Deployments are named after the canonical model id."""

from __future__ import annotations

from app.llms.adapters.base import ChatMessage, Completion
from app.llms.adapters.openai import chat_payload, parse_chat, post_json


class AzureOpenAIAdapter:
    name = "azure_openai"

    def __init__(self, endpoint: str, api_key: str, api_version: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.api_version = api_version

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
        url = f"{self.endpoint}/openai/deployments/{model}/chat/completions?api-version={self.api_version}"
        body = await post_json(
            url,
            {"api-key": self.api_key},
            chat_payload(None, messages, system, max_tokens, json_mode),
            timeout_s,
        )
        return parse_chat(body, "azure_openai", model, self.name)
