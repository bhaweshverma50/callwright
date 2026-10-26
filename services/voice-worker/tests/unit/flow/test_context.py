"""Context strategies and the background summary (004 T075; research R12)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from worker.flow.context import BackgroundSummarizer, Message, handoff, known_facts, last_turns

HISTORY: list[Message] = [
    ("assistant", "Hello"),
    *[m for i in range(8) for m in (("user", f"u{i}"), ("assistant", f"a{i}"))],
]


def test_inherit_keeps_everything() -> None:
    assert handoff("inherit", HISTORY, None, {}).messages == HISTORY


def test_reset_drops_turns_and_keeps_facts() -> None:
    result = handoff("reset", HISTORY, "summary", {"name": "Priya", "empty": ""})
    assert result.messages == [] and result.summary is None
    assert known_facts(result.facts) == "Known facts about this call:\n- name: Priya"


def test_summarize_uses_summary_plus_last_two_turns() -> None:
    result = handoff("summarize", HISTORY, "Caller wants a refund.", {})
    assert result.summary == "Caller wants a refund."
    assert result.messages == [
        ("user", "u6"),
        ("assistant", "a6"),
        ("user", "u7"),
        ("assistant", "a7"),
    ]


def test_summarize_without_summary_falls_back_to_six_turns() -> None:
    result = handoff("summarize", HISTORY, None, {})
    assert result.summary is None and result.messages == last_turns(HISTORY, 6)
    assert result.messages[0] == ("user", "u2")


async def test_summary_runs_in_the_background_and_is_never_awaited() -> None:
    gate = asyncio.Event()

    async def slow(history: Sequence[Message], previous: str | None) -> str:
        await gate.wait()
        return f"{len(history)} messages"

    summarizer = BackgroundSummarizer(slow)
    summarizer.schedule(HISTORY)
    # A handoff now does not wait: no summary yet, so the fallback applies.
    assert handoff("summarize", HISTORY, summarizer.summary, {}).summary is None
    gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert summarizer.summary == f"{len(HISTORY)} messages"
    await summarizer.aclose()


async def test_new_schedule_replaces_a_pending_one() -> None:
    calls: list[int] = []

    async def record(history: Sequence[Message], previous: str | None) -> str:
        calls.append(len(history))
        await asyncio.sleep(0)
        return "s"

    summarizer = BackgroundSummarizer(record)
    summarizer.schedule(HISTORY[:3])
    summarizer.schedule(HISTORY)
    await asyncio.sleep(0.01)
    assert calls[-1] == len(HISTORY)
    await summarizer.aclose()
