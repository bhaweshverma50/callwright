"""Heading-aware chunking (005 T054)."""

from __future__ import annotations

import pytest

from app.knowledge.chunking import TooManyChunks, chunk_blocks, count_tokens
from app.knowledge.extract import Block


def sentence(i: int) -> str:
    return f"Sentence number {i} explains one more detail about the clinic and its patients."


def test_long_section_is_split_near_target_with_overlap() -> None:
    blocks = [Block("heading", "Policies", 1)] + [Block("text", sentence(i), 1 + i // 20) for i in range(80)]
    chunks = chunk_blocks(blocks)
    assert len(chunks) >= 3
    assert all(c.token_count <= 420 for c in chunks)
    assert all(c.token_count >= 200 for c in chunks[:-1])
    assert all(c.heading == "Policies" and c.content.startswith("Policies\n") for c in chunks)
    first_tail = chunks[0].content.splitlines()[-1]
    assert first_tail in chunks[1].content, "consecutive chunks overlap"
    overlap = [line for line in chunks[1].content.splitlines()[1:] if line in chunks[0].content]
    assert 0 < sum(count_tokens(line) for line in overlap) <= 60


def test_heading_starts_a_new_chunk() -> None:
    blocks = [
        Block("heading", "Refunds"),
        Block("text", "Refunds within 14 days."),
        Block("heading", "Hours"),
        Block("text", "Open 8 to 6."),
    ]
    chunks = chunk_blocks(blocks)
    assert [(c.heading, c.content) for c in chunks] == [
        ("Refunds", "Refunds\nRefunds within 14 days."),
        ("Hours", "Hours\nOpen 8 to 6."),
    ]


def test_table_rows_are_never_split() -> None:
    rows = [Block("table_row", f"Service {i} | {i * 10} dollars | " + "detail " * 20) for i in range(40)]
    chunks = chunk_blocks([Block("heading", "Prices"), *rows])
    contents = "\n".join(c.content for c in chunks)
    for row in rows:
        assert any(row.text in c.content for c in chunks)
    assert contents.count("Service 0 |") >= 1


def test_page_ranges() -> None:
    blocks = [Block("text", sentence(i), page) for i, page in enumerate([1, 1, 2, 2, 3])]
    [chunk] = chunk_blocks(blocks)
    assert (chunk.page_from, chunk.page_to) == (1, 3)


def test_chunk_cap() -> None:
    blocks = [Block("text", sentence(i)) for i in range(400)]
    with pytest.raises(TooManyChunks):
        chunk_blocks(blocks, target=40, overlap=0, max_chunks=50)


def test_ordinals_are_sequential() -> None:
    chunks = chunk_blocks([Block("text", sentence(i)) for i in range(100)])
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
