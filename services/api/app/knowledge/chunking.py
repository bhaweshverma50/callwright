"""Heading-aware chunker (T061, research R12).

Target 400 tokens per chunk with a 60-token overlap, counted with ``cl100k_base``. A heading
always starts a new chunk and is repeated at the top of every chunk under it, table rows are
never split, and every chunk keeps its page range and nearest heading. More than 5,000 chunks
in one document raises :class:`TooManyChunks`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache

from app.knowledge.extract import Block
from app.llms.adapters.base import estimate_tokens

TARGET_TOKENS = 400
OVERLAP_TOKENS = 60
MAX_CHUNKS = 5000
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class TooManyChunks(Exception):
    pass


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    content: str
    token_count: int
    page_from: int | None
    page_to: int | None
    heading: str | None


@dataclass(frozen=True)
class _Unit:
    text: str
    tokens: int
    page: int | None
    splittable: bool


@lru_cache(maxsize=1)
def _encoder() -> Callable[[str], list[int]] | None:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:  # offline image without the cached encoding: fall back to an estimate
        return None
    return encoding.encode


def count_tokens(text: str) -> int:
    encode = _encoder()
    if encode is None:
        return estimate_tokens(text)
    return len(encode(text))


def _split_long(text: str, page: int | None, limit: int) -> list[_Unit]:
    """Split prose longer than ``limit`` tokens on sentences, then on words."""
    units: list[_Unit] = []
    for sentence in _SENTENCE.split(text):
        tokens = count_tokens(sentence)
        if tokens <= limit:
            units.append(_Unit(sentence, tokens, page, True))
            continue
        words = sentence.split()
        step = max(1, len(words) * limit // tokens)
        for start in range(0, len(words), step):
            piece = " ".join(words[start : start + step])
            units.append(_Unit(piece, count_tokens(piece), page, True))
    return units


def _tail(units: list[_Unit], budget: int) -> list[_Unit]:
    """Trailing units within ``budget`` tokens; a long last sentence contributes its end."""
    picked: list[_Unit] = []
    used = 0
    for unit in reversed(units):
        if used + unit.tokens > budget:
            if not picked and unit.splittable:
                words = unit.text.split()
                keep = max(1, len(words) * budget // max(unit.tokens, 1))
                text = " ".join(words[-keep:])
                picked.append(_Unit(text, count_tokens(text), unit.page, True))
            break
        picked.append(unit)
        used += unit.tokens
    return list(reversed(picked))


def chunk_blocks(
    blocks: Iterable[Block],
    *,
    target: int = TARGET_TOKENS,
    overlap: int = OVERLAP_TOKENS,
    max_chunks: int = MAX_CHUNKS,
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    heading: str | None = None
    current: list[_Unit] = []
    fresh = 0  # units in ``current`` that are not overlap from the previous chunk

    def emit() -> None:
        nonlocal current, fresh
        if fresh == 0:
            return
        body = "\n".join(u.text for u in current)
        content = f"{heading}\n{body}" if heading else body
        pages = [u.page for u in current if u.page is not None]
        chunks.append(
            ChunkDraft(
                ordinal=len(chunks),
                content=content,
                token_count=count_tokens(content),
                page_from=min(pages) if pages else None,
                page_to=max(pages) if pages else None,
                heading=heading,
            )
        )
        if len(chunks) > max_chunks:
            raise TooManyChunks(f"more than {max_chunks} chunks")
        current = _tail(current, overlap)
        fresh = 0

    for block in blocks:
        if block.kind == "heading":
            emit()
            current, fresh = [], 0
            heading = block.text
            continue
        budget = target - (count_tokens(heading) if heading else 0)
        tokens = count_tokens(block.text)
        if block.kind == "table_row" or tokens <= budget:
            units = [_Unit(block.text, tokens, block.page, block.kind != "table_row")]
        else:
            units = _split_long(block.text, block.page, budget // 2)
        for unit in units:
            used = sum(u.tokens for u in current)
            if current and used + unit.tokens > budget:
                emit()
            current.append(unit)
            fresh += 1
    emit()
    return chunks
