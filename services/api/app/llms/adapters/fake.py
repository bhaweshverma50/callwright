"""Deterministic fake model adapter (T080): dev without vendor keys, and every test.

Token counts are estimated (four characters per token) so feature charges are realistic. Each
feature registers its own deterministic reply for its ``purpose`` in ``PURPOSE_REPLIES``. Test
markers in the last user message: ``[timeout]`` raises ``ModelTimeout``, ``[error]`` raises
``ModelError``.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from app.llms.adapters.base import ChatMessage, Completion, ModelError, ModelTimeout, estimate_tokens

# Deterministic replies the features register for their own ``purpose`` (see their ``register_fakes``).
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
        if purpose in PURPOSE_REPLIES:
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
