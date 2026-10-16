"""Digit-aware end of turn on top of the semantic turn-detector model (research R4).

Callers read account, phone and card numbers in groups with a pause after each group. The
multilingual turn-detector model scores those transcripts inconsistently: in the live
benchmark it held "the account number is four four one nine" for the unfinished-turn wait but
scored "my account number is four four one" as finished, so the agent took the turn in the
700 ms pause before the next group in 8 of 8 calls. :class:`DigitAwareTurnDetector` treats a
transcript that ends in a digit string as unfinished, so the turn waits
``max_endpointing_delay`` (1.22 s at the default responsiveness) and a caller who goes on with
the next group keeps the turn. Everything else is the model's decision.

The wrapper implements the livekit-agents 1.8 turn-detector protocol (``model``, ``provider``,
``unlikely_threshold``, ``supports_language``, ``predict_end_of_turn``) by delegation, so the
framework treats it exactly like the model it wraps.
"""

from __future__ import annotations

import re
from typing import Any

NUMBER_WORDS = frozenset(
    [
        *("zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
        *("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen"),
        *("eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy"),
        *("eighty", "ninety", "hundred", "thousand", "double", "triple"),
    ]
)
_TOKEN = re.compile(r"[a-z0-9']+")


def ends_with_digit_string(text: str) -> bool:
    """True when ``text`` ends in a run of at least two numbers or a multi-digit numeral.

    "four four one" and "4419" are digit strings; "a table for two" is not (one number word
    after ordinary words), so short quantities keep the model's faster decision. A question
    ("where is order A-17?") is not a number being read out, so it is the model's decision too;
    other STT punctuation is ignored because streaming STT puts a full stop on fragments.
    """
    if text.rstrip().endswith("?"):
        return False
    tokens = _TOKEN.findall(text.lower())
    if not tokens:
        return False
    if tokens[-1].isdigit() and len(tokens[-1]) >= 2:
        return True
    run = 0
    for token in reversed(tokens):
        if token in NUMBER_WORDS or token.isdigit():
            run += 1
        else:
            break
    return run >= 2


def last_user_text(chat_ctx: Any) -> str:
    """Text of the newest user message in a framework ``ChatContext`` (empty when none)."""
    for item in reversed(list(getattr(chat_ctx, "items", []) or [])):
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "user":
            return str(getattr(item, "text_content", None) or "")
    return ""


class DigitAwareTurnDetector:
    """Delegates to ``inner`` except that a trailing digit string is never a finished turn."""

    UNFINISHED = 0.0

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    @property
    def model(self) -> str:
        return str(getattr(self.inner, "model", "unknown"))

    @property
    def provider(self) -> str:
        return str(getattr(self.inner, "provider", "unknown"))

    async def unlikely_threshold(self, language: Any) -> float | None:
        threshold: float | None = await self.inner.unlikely_threshold(language)
        return threshold

    async def supports_language(self, language: Any) -> bool:
        return bool(await self.inner.supports_language(language))

    async def predict_end_of_turn(self, chat_ctx: Any, *, timeout: float | None = None) -> float:
        if ends_with_digit_string(last_user_text(chat_ctx)):
            return self.UNFINISHED
        kwargs: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
        probability: float = await self.inner.predict_end_of_turn(chat_ctx, **kwargs)
        return probability
