"""T060: streaming pronunciation transform (research R12, FR-018)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from worker.audio import PronunciationEntry, PronunciationTransform, entries_from_config

ENTRIES = [
    PronunciationEntry("SQL", "sequel"),
    PronunciationEntry("Acme", "Ack-me"),
    PronunciationEntry("New York", "Noo York"),
]


def feed_all(chunks: list[str]) -> str:
    t = PronunciationTransform(ENTRIES)
    return "".join(t.feed(c) for c in chunks) + t.flush()


def test_whole_word_case_insensitive() -> None:
    t = PronunciationTransform(ENTRIES)
    assert t.apply("We use sql and SQL.") == "We use sequel and sequel."
    assert t.apply("ACME rocks") == "Ack-me rocks"


def test_mysql_and_sqlite_untouched() -> None:
    t = PronunciationTransform(ENTRIES)
    assert t.apply("MySQL, SQLite and SQL") == "MySQL, SQLite and sequel"
    assert feed_all(["My", "SQL ", "SQL", "ite ", "SQL"]) == "MySQL SQLite sequel"


@pytest.mark.parametrize(
    "chunks",
    [
        ["Acme uses SQL in New York."],
        ["Ac", "me uses S", "QL in New", " York."],
        ["Acme ", "uses ", "SQL ", "in ", "New ", "York", "."],
        list("Acme uses SQL in New York."),
    ],
)
def test_chunk_boundaries(chunks: list[str]) -> None:
    assert feed_all(chunks) == "Ack-me uses sequel in Noo York."


def test_held_back_text_is_released_on_flush() -> None:
    t = PronunciationTransform(ENTRIES)
    out = t.feed("Call Acme")
    assert "Acme" not in out
    assert out + t.flush() == "Call Ack-me"


def test_no_entries_is_passthrough() -> None:
    t = PronunciationTransform([])
    assert not t.enabled
    assert t.feed("SQL") == "SQL"


def test_entries_from_config_drops_empty_and_duplicates() -> None:
    rows = [
        {"word": "SQL", "replacement": "sequel"},
        {"word": "sql", "replacement": "ess-queue-ell"},
        {"word": "", "replacement": "x"},
        {"word": "Acme", "replacement": " "},
    ]
    assert entries_from_config(rows) == [PronunciationEntry("SQL", "sequel")]
    assert entries_from_config(None) == []


async def test_stream_api() -> None:
    async def source() -> AsyncIterator[str]:
        for chunk in ["Visit Ac", "me today, S", "QL fans"]:
            yield chunk

    t = PronunciationTransform(ENTRIES)
    out = [c async for c in t.stream(source())]
    assert "".join(out) == "Visit Ack-me today, sequel fans"
