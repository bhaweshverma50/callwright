"""The one retry loop for a model reply that must parse: ask, parse, ask once more."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.llms.adapters.base import ChatMessage, Completion, ModelError, ModelTimeout
from app.llms.runtime import CompletionClient

ATTEMPTS = 2


@dataclass
class JsonReply[T]:
    """``value`` is the first parse that worked. ``error`` is the model failure that stopped the
    loop (no retry after a provider failure). Neither set: every reply was unusable.
    ``completions`` holds what each attempt used, for charging."""

    value: T | None = None
    error: Exception | None = None
    completions: list[Completion] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.completions)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.completions)


async def complete_json[T](
    llm: CompletionClient,
    model: str,
    user: str,
    *,
    system: str,
    max_tokens: int,
    timeout_s: float,
    purpose: str,
    parse: Callable[[str], T | None],
) -> JsonReply[T]:
    reply: JsonReply[T] = JsonReply()
    for _attempt in range(ATTEMPTS):
        try:
            completion = await llm.complete(
                model,
                [ChatMessage("user", user)],
                system=system,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                json_mode=True,
                purpose=purpose,
            )
        except (ModelTimeout, ModelError, TimeoutError) as exc:
            reply.error = exc
            return reply
        reply.completions.append(completion)
        reply.value = parse(completion.text)
        if reply.value is not None:
            return reply
    return reply
