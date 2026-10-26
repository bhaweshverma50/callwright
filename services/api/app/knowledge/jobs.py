"""Document ingestion (T064, research R18).

``ingest(deps, doc_id)`` extracts, chunks and embeds one document and, in one transaction,
replaces its chunks, marks it ``ready``, removes the document it replaces and posts the
``knowledge_ingestion`` charge (once per document version: the idempotency key carries the
SHA-256). Permanent errors fail the document with an ``error_code``; transient embedding errors
are retried after 10 s, 60 s and 300 s, then fail with ``embedding_unavailable``. A Redis
counter allows two ingestions per workspace at a time; a third waits and retries.

Where it runs: with S3 storage the arq job ``ingest_document`` runs in the jobs worker. With the
in-memory store (``STORAGE_MODE=fake``, no bucket) only the API process can read the upload, so
:func:`schedule` runs the same code as a background task in the API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any

from opentelemetry import trace
from redis.asyncio import Redis
from sqlalchemy import delete, text
from ulid import ULID

from app.billing import service as billing
from app.core.db import Database
from app.core.errors import ProblemError
from app.core.storage import ObjectStore
from app.knowledge import storage
from app.knowledge.chunking import TooManyChunks, chunk_blocks
from app.knowledge.embeddings import build_embedder
from app.knowledge.embeddings.base import EmbeddingAdapter, EmbeddingUnavailable
from app.knowledge.extract import ExtractError, extract
from app.knowledge.models import Chunk, Document
from app.pricing import service as pricing

log = logging.getLogger(__name__)
tracer = trace.get_tracer("app.knowledge")

JOB_NAME = "ingest_document"
BACKOFF_S: tuple[float, ...] = (10.0, 60.0, 300.0)
SLOT_WAIT_S = 5.0
MAX_CONCURRENT_PER_WORKSPACE = 2
SLOT_TTL_S = 900
EMBED_BATCH = 64
FALLBACK_RATE = ("openai", "text-embedding-3-small")
SIX = Decimal("0.000001")


@dataclass
class IngestDeps:
    db: Database
    redis: Redis | None
    store: ObjectStore
    embedder: EmbeddingAdapter


@dataclass(frozen=True)
class Outcome:
    status: str  # ready | failed | retry | busy | skipped
    retry_in_s: float | None = None


# Concurrency ----------------------------------------------------------------------------------


async def acquire_slot(redis: Redis | None, workspace_id: str) -> bool:
    if redis is None:
        return True
    key = f"kb_ingest_slots:{workspace_id}"
    count = int(await redis.incr(key))
    await redis.expire(key, SLOT_TTL_S)
    if count > MAX_CONCURRENT_PER_WORKSPACE:
        await redis.decr(key)
        return False
    return True


async def release_slot(redis: Redis | None, workspace_id: str) -> None:
    if redis is not None:
        await redis.decr(f"kb_ingest_slots:{workspace_id}")


# Charging -------------------------------------------------------------------------------------


async def ingestion_cost(session: Any, embedder: EmbeddingAdapter, tokens: int) -> tuple[Decimal, Decimal]:
    """(raw, billable) USD for ``tokens`` embedded tokens: tokens / 1000 x catalog rate, with
    the feature markup, rounded up to $0.000001."""
    from app.llms.client import billable_cost

    catalog = await pricing.catalog_at(session)
    rate = catalog.lookup("embedding", embedder.provider, embedder.model) or catalog.lookup(
        "embedding", *FALLBACK_RATE
    )
    per_k = rate.rate_per_min_usd if rate is not None else Decimal(0)
    raw = (Decimal(tokens) / Decimal(1000) * per_k).quantize(SIX, rounding=ROUND_CEILING)
    return raw, billable_cost(raw)


# Ingestion ----------------------------------------------------------------------------------


async def _fail(deps: IngestDeps, doc: Document, code: str, message: str) -> Outcome:
    async with deps.db.transaction(workspace_id=doc.workspace_id) as session:
        row = await session.get(Document, doc.id)
        if row is not None:
            row.status = "failed"
            row.error_code = code
            row.error_message = message
            row.processed_at = datetime.now(UTC)
    return Outcome("failed")


async def workspace_of(db: Database, doc_id: str) -> str | None:
    async with db.transaction() as session:
        found = (
            await session.execute(text("select kb_documents_workspace_for(:id)"), {"id": doc_id})
        ).scalar()
    return str(found) if found is not None else None


async def _load(deps: IngestDeps, doc_id: str) -> Document | None:
    found = await workspace_of(deps.db, doc_id)
    if found is None:
        return None
    async with deps.db.transaction(workspace_id=str(found)) as session:
        doc = await session.get(Document, doc_id)
        if doc is None or doc.status not in ("uploaded", "processing"):
            return None
        doc.status = "processing"
        doc.attempts += 1
        doc.processing_started_at = datetime.now(UTC)
        await session.flush()
        session.expunge(doc)
        return doc


async def ingest(deps: IngestDeps, doc_id: str) -> Outcome:
    with tracer.start_as_current_span("kb.ingest") as span:
        span.set_attribute("kb.doc_id", doc_id)
        doc = await _load(deps, doc_id)
        if doc is None:
            return Outcome("skipped")
        if not await acquire_slot(deps.redis, doc.workspace_id):
            async with deps.db.transaction(workspace_id=doc.workspace_id) as session:
                row = await session.get(Document, doc.id)
                if row is not None:
                    row.attempts = max(0, row.attempts - 1)
            return Outcome("busy", SLOT_WAIT_S)
        try:
            return await _ingest(deps, doc, span)
        finally:
            await release_slot(deps.redis, doc.workspace_id)


async def _ingest(deps: IngestDeps, doc: Document, span: Any) -> Outcome:
    data = await storage.read(deps.store, doc.storage_key)
    if data is None:
        return await _fail(
            deps, doc, "internal", "The uploaded file is no longer available. Upload it again."
        )
    try:
        extracted = await asyncio.to_thread(extract, data, doc.file_type)
        drafts = await asyncio.to_thread(chunk_blocks, extracted.blocks)
    except ExtractError as exc:
        return await _fail(deps, doc, exc.code, exc.message)
    except TooManyChunks:
        return await _fail(
            deps, doc, "too_many_chunks", "The document is too long: split it into smaller files."
        )
    if not drafts:
        return await _fail(deps, doc, "no_extractable_text", "No text could be read from the document.")
    try:
        vectors: list[list[float]] = []
        texts = [d.content for d in drafts]
        for start in range(0, len(texts), EMBED_BATCH):
            vectors += await deps.embedder.embed(texts[start : start + EMBED_BATCH])
    except EmbeddingUnavailable as exc:
        attempt = doc.attempts
        if attempt <= len(BACKOFF_S):
            async with deps.db.transaction(workspace_id=doc.workspace_id) as session:
                row = await session.get(Document, doc.id)
                if row is not None:
                    row.status = "uploaded"
            log.warning("embedding unavailable for %s (attempt %s): %s", doc.id, attempt, exc)
            return Outcome("retry", BACKOFF_S[attempt - 1])
        return await _fail(
            deps,
            doc,
            "embedding_unavailable",
            "The embedding service is unavailable. Retry in a few minutes.",
        )
    tokens = sum(d.token_count for d in drafts)
    span.set_attribute("kb.chunk_count", len(drafts))
    span.set_attribute("kb.token_count", tokens)
    replaced_key: str | None = None
    try:
        async with deps.db.transaction(workspace_id=doc.workspace_id) as session:
            row = await session.get(Document, doc.id, with_for_update=True)
            if row is None:
                return Outcome("skipped")
            await session.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
            session.add_all(
                Chunk(
                    id=str(ULID()),
                    workspace_id=doc.workspace_id,
                    kb_id=doc.kb_id,
                    doc_id=doc.id,
                    ordinal=d.ordinal,
                    content=d.content,
                    token_count=d.token_count,
                    page_from=d.page_from,
                    page_to=d.page_to,
                    heading=d.heading,
                    embedding=vector,
                    embedding_model=deps.embedder.model,
                )
                for d, vector in zip(drafts, vectors, strict=True)
            )
            raw, billable = await ingestion_cost(session, deps.embedder, tokens)
            await billing.charge_feature(
                session,
                workspace_id=doc.workspace_id,
                feature_key="knowledge_ingestion",
                quantity=Decimal(tokens),
                unit="tokens",
                raw_cost_usd=raw,
                billable_cost_usd=billable,
                idempotency_key=f"kb_ingest:{doc.id}:{doc.sha256}",
                ref_type="kb_document",
                ref_id=doc.id,
            )
            row.status = "ready"
            row.error_code = None
            row.error_message = None
            row.page_count = extracted.page_count
            row.chunk_count = len(drafts)
            row.token_count = tokens
            row.embedding_model = deps.embedder.model
            row.processed_at = datetime.now(UTC)
            if row.replaces_doc_id:
                old = await session.get(Document, row.replaces_doc_id)
                if old is not None and old.kb_id == row.kb_id:
                    replaced_key = old.storage_key
                    await session.delete(old)
    except ProblemError as exc:
        if exc.code == "insufficient_credit":
            return await _fail(
                deps, doc, "internal", "Not enough credit to process this document. Top up, then retry."
            )
        raise
    if replaced_key:
        with contextlib.suppress(Exception):
            await storage.delete(deps.store, replaced_key)
    return Outcome("ready")


# Scheduling ---------------------------------------------------------------------------------

Sleep = Callable[[float], Awaitable[None]]
_inline_tasks: set[asyncio.Task[Any]] = set()


async def run_inline(deps: IngestDeps, doc_id: str, sleep: Sleep = asyncio.sleep) -> Outcome:
    """Ingest in this process, waiting out retries and busy slots (in-memory storage mode)."""
    while True:
        try:
            outcome = await ingest(deps, doc_id)
        except Exception:
            log.exception("ingestion of %s crashed", doc_id)
            ws = await workspace_of(deps.db, doc_id)
            if ws is not None:
                async with deps.db.transaction(workspace_id=str(ws)) as session:
                    row = await session.get(Document, doc_id)
                    if row is not None and row.status != "ready":
                        row.status, row.error_code = "failed", "internal"
                        row.error_message = "Processing failed. Retry the document."
            return Outcome("failed")
        if outcome.retry_in_s is None:
            return outcome
        await sleep(outcome.retry_in_s)


def deps_from_state(state: Any) -> IngestDeps:
    embedder = getattr(state, "embedder", None)
    if embedder is None:
        embedder = build_embedder(state.settings)
        state.embedder = embedder
    return IngestDeps(db=state.db, redis=state.redis, store=state.storage, embedder=embedder)


async def schedule(state: Any, doc_id: str) -> None:
    """Start ingestion of ``doc_id`` after its upload committed."""
    if storage.is_in_memory(state.storage):
        task = asyncio.create_task(run_inline(deps_from_state(state), doc_id))
        _inline_tasks.add(task)
        task.add_done_callback(_inline_tasks.discard)
        return
    await state.jobs.enqueue(JOB_NAME, doc_id, job_id=f"{JOB_NAME}:{doc_id}:{ULID()}")


async def drain() -> None:
    """Wait for in-process ingestions (tests, shutdown)."""
    while _inline_tasks:
        await asyncio.gather(*list(_inline_tasks), return_exceptions=True)


async def ingest_document(ctx: dict[str, Any], doc_id: str) -> str:
    """arq job: one attempt; retries and busy slots re-enqueue with a delay."""
    from app.core.storage import build_store

    if "kb_deps" not in ctx:
        settings = ctx["settings"]
        ctx["kb_deps"] = IngestDeps(
            db=ctx["db"],
            redis=ctx.get("redis"),
            store=build_store(settings),
            embedder=build_embedder(settings),
        )
    outcome = await ingest(ctx["kb_deps"], doc_id)
    if outcome.retry_in_s is not None:
        await ctx["jobs"].enqueue(
            JOB_NAME, doc_id, defer_by_s=outcome.retry_in_s, job_id=f"{JOB_NAME}:{doc_id}:{ULID()}"
        )
    return outcome.status
