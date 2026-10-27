"""Scriptable LLM client for 007 tests (T005).

Answers, in order of precedence: the next scripted reply (``replies``), a fixture looked up by
the prompt hash (``fixtures``, see ``prompt_hash``), then ``responder(system, user, purpose)``.
A reply of ``"[timeout]"`` or ``"[error]"`` raises the matching model exception. Every request
is recorded in ``calls`` so tests can inspect the exact framing sent to the model.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.llms.adapters.base import ChatMessage, Completion, ModelError, ModelTimeout, estimate_tokens

Responder = Callable[[str, str, str | None], str]


def prompt_hash(system: str | None, messages: list[ChatMessage]) -> str:
    body = (system or "") + "\x00" + "\x00".join(f"{m.role}:{m.content}" for m in messages)
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass
class FakeLlm:
    responder: Responder | None = None
    fixtures: dict[str, str] = field(default_factory=dict)
    replies: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self,
        ref: Any,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        timeout_s: float = 60.0,
        json_mode: bool = False,
        purpose: str | None = None,
    ) -> Completion:
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        self.calls.append({"ref": str(ref), "system": system or "", "user": user, "purpose": purpose})
        if self.replies:
            text = self.replies.pop(0)
        elif (key := prompt_hash(system, messages)) in self.fixtures:
            text = self.fixtures[key]
        elif self.responder is not None:
            text = self.responder(system or "", user, purpose)
        else:
            raise AssertionError(f"FakeLlm has no answer for purpose={purpose}")
        if text == "[timeout]":
            raise ModelTimeout("fake timeout")
        if text == "[error]":
            raise ModelError("fake error")
        model = str(ref).partition("/")[2] or str(ref)
        return Completion(
            text=text,
            input_tokens=estimate_tokens((system or "") + user),
            output_tokens=estimate_tokens(text),
            provider="fake",
            model=model,
            adapter="fake",
        )
