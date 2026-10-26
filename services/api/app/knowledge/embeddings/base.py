"""Embedding adapter port (T062, research R13). Vendors live in sibling modules."""

from __future__ import annotations

from typing import Protocol

DIMENSIONS = 1536


class EmbeddingUnavailable(Exception):
    """Transient vendor failure (timeout, rate limit, 5xx): the caller may retry."""


class EmbeddingAdapter(Protocol):
    provider: str
    model: str
    dimensions: int
    # Cosine similarity below which retrieval drops a passage, tuned per model (R14).
    similarity_threshold: float

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def aclose(self) -> None: ...
