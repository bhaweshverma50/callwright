"""Agent goodbye detection (hang up after the agent's goodbye without waiting for the caller)."""

from __future__ import annotations

import pytest

from worker.call_behavior import ends_with_goodbye


@pytest.mark.parametrize(
    "text",
    [
        "Thanks again for your time today. Have a good day, goodbye.",
        "Have a great day, goodbye!",
        "Okay, bye now.",
        "Thanks Jordan. Take care.",
        "Thanks for calling, have a wonderful evening",
        "Good-bye!",
    ],
)
def test_goodbye_endings(text: str) -> None:
    assert ends_with_goodbye(text)


@pytest.mark.parametrize(
    "text",
    [
        "Before I say goodbye, can you confirm your date of birth?",
        "Is there anything else I can help with?",
        "Goodbye is not what I meant. Let me check that payment for you.",
        "",
    ],
)
def test_not_goodbye(text: str) -> None:
    assert not ends_with_goodbye(text)
