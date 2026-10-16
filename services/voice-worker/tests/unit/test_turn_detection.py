"""Digit-aware turn detection (research R4)."""

from __future__ import annotations

from typing import Any

import pytest
from livekit.agents import llm

from worker.turn_detection import DigitAwareTurnDetector, ends_with_digit_string, last_user_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("My account number is four four one", True),
        ("The account number is four four one nine.", True),
        ("my phone number is nine eight four", True),
        ("It is 4419", True),
        ("born in nineteen ninety", True),
        ("Card ending double oh seven.", True),
        ("A table for two.", False),
        ("Where is my order A-17?", False),
        ("My order is A-17", True),
        ("I have 3 kids", False),
        ("I would like to change my address.", False),
        ("Four four one and that is all", False),
        ("", False),
    ],
)
def test_ends_with_digit_string(text: str, expected: bool) -> None:
    assert ends_with_digit_string(text) is expected


class FakeModel:
    model = "multilingual"
    provider = "livekit"

    def __init__(self, probability: float) -> None:
        self.probability = probability
        self.calls: list[dict[str, Any]] = []

    async def unlikely_threshold(self, language: Any) -> float | None:
        return 0.2

    async def supports_language(self, language: Any) -> bool:
        return bool(language == "en")

    async def predict_end_of_turn(self, chat_ctx: Any, **kwargs: Any) -> float:
        self.calls.append(kwargs)
        return self.probability


def ctx(*user_texts: str) -> llm.ChatContext:
    chat = llm.ChatContext()
    chat.add_message(role="assistant", content="How can I help?")
    for text in user_texts:
        chat.add_message(role="user", content=text)
    return chat


async def test_digit_string_is_unfinished_without_asking_the_model() -> None:
    inner = FakeModel(0.97)
    detector = DigitAwareTurnDetector(inner)
    assert await detector.predict_end_of_turn(ctx("My account number is four four one")) == 0.0
    assert inner.calls == []
    threshold = await detector.unlikely_threshold("en")
    assert threshold is not None and threshold > 0.0


async def test_other_turns_are_the_models_decision() -> None:
    inner = FakeModel(0.97)
    detector = DigitAwareTurnDetector(inner)
    assert await detector.predict_end_of_turn(ctx("A table for two."), timeout=3) == 0.97
    assert inner.calls == [{"timeout": 3}]
    assert await detector.supports_language("en")
    assert not await detector.supports_language("xx")
    assert (detector.model, detector.provider) == ("multilingual", "livekit")


def test_last_user_text_reads_the_newest_user_message() -> None:
    assert last_user_text(ctx("first", "second one")) == "second one"
    assert last_user_text(llm.ChatContext()) == ""
