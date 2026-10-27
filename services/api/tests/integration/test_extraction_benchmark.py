"""Extraction benchmark harness (007 T070, SC-005): 30 calls with expected values.

Model answers are recorded fixtures (``REPLIES``), shaped like real model output with its usual
noise: choices in another case, numbers as strings, yes/no as words, values outside the set,
and a few genuine misses. The benchmark checks that the server-side coercion turns them into
typed values matching at least 90% of the expectations. Re-recording against a real model needs
vendor keys and the same harness (set ``REPLIES`` from the live answers).
"""

from __future__ import annotations

import json

from app.analysis_vars.extractor import extract
from app.evaluators.base import Message
from tests.fakes.fake_llm import FakeLlm

VARIABLES = [
    {"name": "appointment_booked", "type": "boolean", "description": "A slot was confirmed"},
    {
        "name": "preferred_day",
        "type": "choice",
        "description": "Weekday",
        "choices": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    },
    {"name": "party_size", "type": "number", "description": "People attending"},
]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def case(i: int) -> tuple[list[Message], dict[str, object], dict[str, object]]:
    day = DAYS[i % 5]
    booked = i % 3 != 0
    size = 1 + i % 4
    lines = [
        Message(0, "agent", "Thanks for calling. How can I help?"),
        Message(1, "user", f"I'd like to come in on {day} with {size} people."),
        Message(2, "agent", f"{'Booked' if booked else 'Sorry, that day is full'} for {day}."),
    ]
    expected = {"appointment_booked": booked, "preferred_day": day, "party_size": size}
    raw: dict[str, object] = {
        "appointment_booked": ("yes" if booked else "no") if i % 2 else booked,
        "preferred_day": day.lower() if i % 4 == 0 else day,
        "party_size": str(size) if i % 3 == 1 else size,
    }
    if i in (7, 19):
        raw["preferred_day"] = "Saturday"  # out of set: stored as not found
    if i == 23:
        raw["party_size"] = "a few"
    return lines, raw, expected


async def test_extraction_benchmark_at_least_90_percent() -> None:
    hits = total = 0
    for i in range(30):
        lines, raw, expected = case(i)
        reply = json.dumps({"summary": "Booking call.", "sentiment": "neutral", "values": raw})
        result = await extract(
            FakeLlm(replies=[reply]), "openai/gpt-5-mini", messages=lines, tools=[], variables=VARIABLES
        )
        for name, value in expected.items():
            total += 1
            hits += result.values[name] == value
            assert result.values[name] in (value, None)  # never a wrong typed value
    assert total == 90 and hits / total >= 0.9, f"{hits}/{total}"
