"""Types shared by the API-side model adapters (T080, Principle I)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    adapter: str


class ModelTimeout(Exception):
    """The vendor did not answer in time."""


class ModelError(Exception):
    """The vendor call failed (network, auth, malformed response)."""


class LlmAdapter(Protocol):
    name: str

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
    ) -> Completion: ...


def estimate_tokens(text: str) -> int:
    """Rough token count (four characters per token), used by the fake adapter."""
    return max(1, -(-len(text) // 4))
