"""The mass-archive guard (022 FR-014, research R9). Pure apart from ``active_documents``.

One sync may archive at most ``max(2, floor(20% of the source's active documents))``. Over that,
it archives none of them and holds the whole set for the operator to confirm or cancel, so a
folder emptied by mistake never empties the knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import Document

SHARE = 0.20
ALWAYS_ALLOWED = 2


@dataclass(frozen=True)
class Archive:
    doc_ids: list[str]


@dataclass(frozen=True)
class Hold:
    doc_ids: list[str]
    would_archive: int
    of: int


def allowance(active: int) -> int:
    return max(ALWAYS_ALLOWED, int(active * SHARE))


def decide(doc_ids: list[str], active: int) -> Archive | Hold:
    if len(doc_ids) <= allowance(active):
        return Archive(list(doc_ids))
    return Hold(list(doc_ids), len(doc_ids), active)


def message(would_archive: int, of: int) -> str:
    return f"This sync would archive {would_archive} of {of} documents"


async def active_documents(session: AsyncSession, source_id: str) -> int:
    """Documents of the source still serving or about to serve search (not archived or failed)."""
    count = await session.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.source_id == source_id, Document.status.in_(("ready", "processing", "uploaded")))
    )
    return int(count.scalar_one())
