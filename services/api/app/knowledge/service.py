"""Knowledge bases: CRUD, uploads, duplicates, attach sets, deletion and search (T063, T075).

Every function takes an ``AsyncSession`` scoped to the workspace (RLS). Interfaces for others:

* ``describe_for_snapshot(session, kb_ids)``: ``[{kb_id, name, description}]`` for the version
  snapshot (registered as 002's ``knowledge`` resolver), used to word ``kb_search``.
* ``search(...)``: the retrieval used by calls (internal endpoint) and the KB page preview.
"""

from __future__ import annotations

import hashlib
import struct
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service as agents
from app.core.db import escape_like
from app.core.errors import ProblemError, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.core.pagination import page_window
from app.core.storage import ObjectStore
from app.knowledge import storage
from app.knowledge.extract import sniff
from app.knowledge.models import Document, KnowledgeBase
from app.llms.embeddings.base import EmbeddingAdapter

tracer = trace.get_tracer("app.knowledge")

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_DOCS_PER_KB = 200
MAX_WORKSPACE_BYTES = 1024 * 1024 * 1024
QUERY_CACHE_TTL_S = 24 * 3600
MAX_RESULT_CHARS = 4000
EF_SEARCH = 40


def kb_in_use(rows: Sequence[tuple[str, str]]) -> ProblemError:
    return ProblemError(
        409,
        "knowledge_base_in_use",
        "Knowledge base is in use",
        "These agents use the knowledge base. Confirm to detach it from their drafts and delete it.",
        extra={"agents": [{"agent_id": a, "agent_name": n} for a, n in rows]},
    )


def file_too_large() -> ProblemError:
    return ProblemError(413, "file_too_large", "File too large", "Files can be at most 20 MB.")


def unsupported_type() -> ProblemError:
    return ProblemError(
        415, "unsupported_file_type", "Unsupported file type", "Upload a PDF or a Word (.docx) document."
    )


def quota_exceeded(detail: str) -> ProblemError:
    return ProblemError(422, "quota_exceeded", "Quota exceeded", detail)


@dataclass(frozen=True)
class Counts:
    document_count: int = 0
    ready_count: int = 0
    processing_count: int = 0
    failed_count: int = 0
    total_bytes: int = 0
    agent_count: int = 0
    archived_count: int = 0
    source_count: int = 0

    @property
    def status(self) -> str:
        if self.document_count == 0:
            return "empty"
        if self.processing_count:
            return "processing"
        if self.failed_count and self.ready_count:
            return "partial"
        if self.failed_count:
            return "failed"
        return "ready"


async def counts_for(session: AsyncSession, kb_ids: Sequence[str]) -> dict[str, Counts]:
    if not kb_ids:
        return {}
    rows = (
        await session.execute(
            text("""
            SELECT k.id,
                   count(d.id) FILTER (WHERE d.status <> 'archived'),
                   count(d.id) FILTER (WHERE d.status = 'ready'),
                   count(d.id) FILTER (WHERE d.status IN ('uploaded', 'processing')),
                   count(d.id) FILTER (WHERE d.status = 'failed'),
                   coalesce(sum(d.file_size), 0),
                   (SELECT count(*) FROM agents a WHERE a.deleted_at IS NULL
                      AND a.draft_config @> jsonb_build_object('kb_ids', jsonb_build_array(k.id))),
                   count(d.id) FILTER (WHERE d.status = 'archived'),
                   (SELECT count(*) FROM kb_sources s WHERE s.kb_id = k.id)
              FROM knowledge_bases k
              LEFT JOIN kb_documents d ON d.kb_id = k.id
             WHERE k.id = ANY(CAST(:ids AS text[]))
             GROUP BY k.id
            """),
            {"ids": list(kb_ids)},
        )
    ).all()
    return {str(r[0]): Counts(*(int(v) for v in r[1:])) for r in rows}


def kb_view(kb: KnowledgeBase, counts: Counts) -> dict[str, Any]:
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "status": counts.status,
        "attachable": counts.ready_count > 0,
        "document_count": counts.document_count,
        "ready_count": counts.ready_count,
        "processing_count": counts.processing_count,
        "failed_count": counts.failed_count,
        "archived_count": counts.archived_count,
        "source_count": counts.source_count,
        "total_bytes": counts.total_bytes,
        "agent_count": counts.agent_count,
        "created_at": kb.created_at.isoformat(),
        "updated_at": kb.updated_at.isoformat(),
    }


async def kb_views(session: AsyncSession, kbs: Sequence[KnowledgeBase]) -> list[dict[str, Any]]:
    counts = await counts_for(session, [k.id for k in kbs])
    return [kb_view(k, counts.get(k.id, Counts())) for k in kbs]


def document_view(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "kb_id": doc.kb_id,
        "file_name": doc.file_name,
        "display_name": doc.display_name,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "sha256": doc.sha256,
        "status": doc.status,
        "error_code": doc.error_code,
        "error_message": doc.error_message,
        "page_count": doc.page_count,
        "chunk_count": doc.chunk_count,
        "replaces_doc_id": doc.replaces_doc_id,
        "created_at": doc.created_at.isoformat(),
        "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
        "archived_at": doc.archived_at.isoformat() if doc.archived_at else None,
        "managed": doc.source_id is not None,
        "source": None,
    }


def _name_taken(name: str) -> ProblemError:
    return ProblemError(
        409, "name_taken", "Name in use", f"A knowledge base named {name} already exists in this workspace."
    )


async def _check_name(session: AsyncSession, name: str, exclude: str | None = None) -> None:
    query = select(KnowledgeBase.id).where(func.lower(KnowledgeBase.name) == name.strip().lower())
    if exclude:
        query = query.where(KnowledgeBase.id != exclude)
    if (await session.execute(query)).first() is not None:
        raise _name_taken(name)


async def create_kb(session: AsyncSession, actor: agents.Actor, name: str, description: str) -> KnowledgeBase:
    name = name.strip()
    if not name:
        raise validation_failed([{"pointer": "/name", "code": "required", "message": "Enter a name."}])
    await _check_name(session, name)
    kb = KnowledgeBase(
        id=new_id("kb"),
        workspace_id=actor.workspace_id,
        name=name,
        description=description.strip(),
        created_by=actor.user_id,
    )
    session.add(kb)
    await session.flush()
    await session.refresh(kb)
    return kb


async def get_kb(session: AsyncSession, kb_id: str) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id) if is_valid_id(kb_id, "kb") else None
    if kb is None:
        raise not_found("knowledge base")
    return kb


async def update_kb(
    session: AsyncSession, kb_id: str, name: str | None, description: str | None
) -> KnowledgeBase:
    kb = await get_kb(session, kb_id)
    if name is not None and name.strip() != kb.name:
        if not name.strip():
            raise validation_failed([{"pointer": "/name", "code": "required", "message": "Enter a name."}])
        await _check_name(session, name, exclude=kb.id)
        kb.name = name.strip()
    if description is not None:
        kb.description = description.strip()
    kb.updated_at = datetime.now(UTC)
    await session.flush()
    return kb


async def list_kbs(
    session: AsyncSession, *, search: str | None, attachable: bool | None, page: int, page_size: int
) -> tuple[list[KnowledgeBase], int]:
    query = select(KnowledgeBase)
    if search:
        query = query.where(
            func.lower(KnowledgeBase.name).like(f"%{escape_like(search.lower())}%", escape="\\")
        )
    if attachable is not None:
        ready = (
            select(Document.id).where(Document.kb_id == KnowledgeBase.id, Document.status == "ready").exists()
        )
        query = query.where(ready if attachable else ~ready)
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = (
        await session.execute(
            query.order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id.desc()).slice(
                *page_window(page, page_size)
            )
        )
    ).scalars()
    return list(rows), total


async def agents_using(session: AsyncSession, kb_id: str) -> list[tuple[str, str]]:
    rows = (
        await session.execute(
            text("""
            SELECT id, name FROM agents
             WHERE deleted_at IS NULL
               AND draft_config @> jsonb_build_object('kb_ids', jsonb_build_array(CAST(:kb AS text)))
             ORDER BY name, id
            """),
            {"kb": kb_id},
        )
    ).all()
    return [(str(r[0]), str(r[1])) for r in rows]


async def delete_kb(
    session: AsyncSession, actor: agents.Actor, store: ObjectStore, kb_id: str, *, confirm: bool
) -> list[str]:
    kb = await get_kb(session, kb_id)
    users = await agents_using(session, kb_id)
    if users and not confirm:
        raise kb_in_use(users)
    await agents.detach(session, actor, "kb_ids", kb_id, [a for a, _ in users])
    keys = list(
        (await session.execute(select(Document.storage_key).where(Document.kb_id == kb_id))).scalars()
    )
    await session.delete(kb)
    await session.flush()
    for key in keys:
        await storage.delete(store, key)
    return [a for a, _ in users]


async def get_document(session: AsyncSession, kb_id: str, doc_id: str) -> Document:
    await get_kb(session, kb_id)
    doc = await session.get(Document, doc_id) if is_valid_id(doc_id, "doc") else None
    if doc is None or doc.kb_id != kb_id:
        raise not_found("document")
    return doc


async def list_documents(
    session: AsyncSession, kb_id: str, *, status: str | None, page: int, page_size: int
) -> tuple[list[Document], int]:
    await get_kb(session, kb_id)
    query = select(Document).where(Document.kb_id == kb_id)
    if status:
        query = query.where(Document.status == status)
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = (
        await session.execute(
            query.order_by(Document.created_at.desc(), Document.id.desc()).slice(
                *page_window(page, page_size)
            )
        )
    ).scalars()
    return list(rows), total


@dataclass(frozen=True)
class DuplicateMatch:
    kb_id: str
    kb_name: str
    doc_id: str
    file_name: str
    reason: str


async def duplicate_matches(
    session: AsyncSession, kb_id: str, file_name: str, sha256: str
) -> tuple[str, list[DuplicateMatch]]:
    """Verdict ``blocked_same_kb``, ``warn_other_kb``, ``warn_same_name`` or ``ok`` (R11)."""
    rows = (
        await session.execute(
            select(Document, KnowledgeBase.name)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(
                (Document.sha256 == sha256)
                | ((Document.kb_id == kb_id) & (func.lower(Document.file_name) == file_name.lower()))
            )
        )
    ).all()
    matches = [
        DuplicateMatch(
            kb_id=doc.kb_id,
            kb_name=str(kb_name),
            doc_id=doc.id,
            file_name=doc.file_name,
            reason="same_content" if doc.sha256 == sha256 else "same_name",
        )
        for doc, kb_name in rows
    ]
    if any(m.reason == "same_content" and m.kb_id == kb_id for m in matches):
        verdict = "blocked_same_kb"
    elif any(m.reason == "same_content" for m in matches):
        verdict = "warn_other_kb"
    elif matches:
        verdict = "warn_same_name"
    else:
        verdict = "ok"
    return verdict, matches


@dataclass(frozen=True)
class Upload:
    file_name: str
    data: bytes
    display_name: str | None = None
    replace_doc_id: str | None = None
    acknowledge_duplicate: bool = False


async def create_document(
    session: AsyncSession, actor: agents.Actor, store: ObjectStore, kb_id: str, upload: Upload
) -> Document:
    """Validate and store an upload; the caller enqueues ingestion after commit."""
    await get_kb(session, kb_id)
    data = upload.data
    if len(data) > MAX_FILE_BYTES:
        raise file_too_large()
    if not data:
        raise validation_failed([{"pointer": "/file", "code": "required", "message": "The file is empty."}])
    file_type = sniff(data)
    if file_type is None:
        raise unsupported_type()
    sha256 = hashlib.sha256(data).hexdigest()
    verdict, matches = await duplicate_matches(session, kb_id, upload.file_name, sha256)
    if verdict == "blocked_same_kb":
        raise ProblemError(
            409,
            "duplicate_document",
            "Already uploaded",
            "This knowledge base already has a document with the same content.",
            extra={"matches": [m.__dict__ for m in matches if m.reason == "same_content"]},
        )
    if verdict == "warn_other_kb" and not upload.acknowledge_duplicate:
        raise ProblemError(
            409,
            "duplicate_elsewhere",
            "Same content elsewhere",
            "The same document is in another knowledge base. Upload again to keep both.",
            extra={"matches": [m.__dict__ for m in matches if m.reason == "same_content"]},
        )
    if upload.replace_doc_id is not None:
        await get_document(session, kb_id, upload.replace_doc_id)
    count = int(
        (
            await session.execute(select(func.count()).select_from(Document).where(Document.kb_id == kb_id))
        ).scalar_one()
    )
    if count >= MAX_DOCS_PER_KB:
        raise quota_exceeded(f"A knowledge base can hold at most {MAX_DOCS_PER_KB} documents.")
    used = int((await session.execute(select(func.coalesce(func.sum(Document.file_size), 0)))).scalar_one())
    if used + len(data) > MAX_WORKSPACE_BYTES:
        raise quota_exceeded("This workspace has reached its 1 GB document storage limit.")
    doc_id = new_id("doc")
    file_name = upload.file_name.strip()[:255] or f"document.{file_type}"
    key = storage.document_key(actor.workspace_id, kb_id, doc_id, sha256, file_type)
    doc = Document(
        id=doc_id,
        workspace_id=actor.workspace_id,
        kb_id=kb_id,
        file_name=file_name,
        display_name=(upload.display_name or "").strip()[:255] or file_name,
        file_type=file_type,
        file_size=len(data),
        sha256=sha256,
        storage_key=key,
        status="uploaded",
        replaces_doc_id=upload.replace_doc_id,
        uploaded_by=actor.user_id,
    )
    session.add(doc)
    await session.flush()
    await storage.put(store, key, data, file_type)
    await session.refresh(doc)
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is not None:
        kb.updated_at = datetime.now(UTC)
    return doc


async def delete_document(session: AsyncSession, store: ObjectStore, kb_id: str, doc_id: str) -> None:
    doc = await get_document(session, kb_id, doc_id)
    key = doc.storage_key
    await session.delete(doc)
    await session.flush()
    await storage.delete(store, key)


async def reprocess(session: AsyncSession, kb_id: str, doc_id: str) -> Document:
    doc = await get_document(session, kb_id, doc_id)
    if doc.status != "failed":
        raise ProblemError(
            409, "not_failed", "Nothing to retry", "Only failed documents can be processed again."
        )
    doc.status = "uploaded"
    doc.error_code = None
    doc.error_message = None
    doc.attempts = 0
    await session.flush()
    return doc


async def kbs_by_id(session: AsyncSession, kb_ids: Sequence[str]) -> dict[str, KnowledgeBase]:
    valid = [k for k in kb_ids if is_valid_id(k, "kb")]
    if not valid:
        return {}
    rows = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(valid)))).scalars()
    return {k.id: k for k in rows}


async def agent_kbs(session: AsyncSession, agent_id: str) -> list[KnowledgeBase]:
    agent = await agents.get_agent(session, agent_id)
    ids = list(agent.draft_config.get("kb_ids") or [])
    found = await kbs_by_id(session, ids)
    return [found[k] for k in ids if k in found]


async def set_agent_kbs(
    session: AsyncSession, actor: agents.Actor, agent_id: str, kb_ids: list[str]
) -> list[KnowledgeBase]:
    agent = await agents.get_agent(session, agent_id)
    agents.check_attach_count("kb_ids", kb_ids)
    found = await kbs_by_id(session, kb_ids)
    missing = [
        {
            "pointer": f"/kb_ids/{i}",
            "code": "missing_reference",
            "message": "This knowledge base no longer exists.",
        }
        for i, k in enumerate(kb_ids)
        if k not in found
    ]
    if missing:
        raise validation_failed(missing)
    already = set(agent.draft_config.get("kb_ids") or [])
    counts = await counts_for(session, kb_ids)
    not_ready = [k for k in kb_ids if k not in already and counts.get(k, Counts()).ready_count == 0]
    if not_ready:
        names = ", ".join(found[k].name for k in not_ready)
        raise ProblemError(
            422,
            "knowledge_base_not_ready",
            "Knowledge base not ready",
            f"{names} has no processed documents yet. Attach it once a document is ready.",
            errors=[
                {
                    "pointer": f"/kb_ids/{kb_ids.index(k)}",
                    "code": "knowledge_base_not_ready",
                    "message": "Not ready",
                }
                for k in not_ready
            ],
        )
    await agents.attach(session, actor, agent_id, "kb_ids", kb_ids)
    return [found[k] for k in kb_ids]


async def describe_for_snapshot(session: AsyncSession, kb_ids: Sequence[str]) -> list[dict[str, str]]:
    found = await kbs_by_id(session, kb_ids)
    return [
        {"kb_id": k, "name": found[k].name, "description": found[k].description} for k in kb_ids if k in found
    ]


def _normalize(query: str) -> str:
    return " ".join(query.lower().split())


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


async def query_embedding(
    redis: Redis | None, embedder: EmbeddingAdapter, query: str
) -> tuple[list[float], bool]:
    key = f"kbq:{embedder.model}:{hashlib.sha256(_normalize(query).encode()).hexdigest()}"
    if redis is not None:
        cached = await redis.get(key)
        if cached:
            return _unpack(bytes(cached)), True
    [vector] = await embedder.embed([query])
    if redis is not None:
        await redis.set(key, _pack(vector), ex=QUERY_CACHE_TTL_S)
    return vector, False


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


_SEARCH_SQL = text("""
    SELECT c.id, c.kb_id, c.doc_id, d.display_name, c.page_from, c.page_to, c.heading, c.content,
           1 - (c.embedding <=> CAST(:q AS vector)) AS score
      FROM kb_chunks c
      JOIN kb_documents d ON d.id = c.doc_id
     WHERE c.kb_id = ANY(CAST(:kb_ids AS text[]))
       AND c.embedding_model = :model
       AND d.status = 'ready'
     ORDER BY c.embedding <=> CAST(:q AS vector)
     LIMIT :top_k
""")


async def search(
    session: AsyncSession,
    redis: Redis | None,
    embedder: EmbeddingAdapter,
    kb_ids: Sequence[str],
    query: str,
    top_k: int = 4,
) -> dict[str, Any]:
    with tracer.start_as_current_span("kb.search") as span:
        span.set_attribute("kb.count", len(kb_ids))
        started = time.perf_counter()
        vector, cache_hit = await query_embedding(redis, embedder, query)
        embedded = time.perf_counter()
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rows = (
            await session.execute(
                _SEARCH_SQL,
                {
                    "q": vector_literal(vector),
                    "kb_ids": list(kb_ids),
                    "model": embedder.model,
                    "top_k": top_k,
                },
            )
        ).all()
        finished = time.perf_counter()
        results: list[dict[str, Any]] = []
        budget = MAX_RESULT_CHARS
        for row in rows:
            score = max(0.0, min(1.0, float(row[8])))
            if score < embedder.similarity_threshold or budget <= 0:
                continue
            content = str(row[7])[:budget]
            budget -= len(content)
            results.append(
                {
                    "chunk_id": row[0],
                    "kb_id": row[1],
                    "doc_id": row[2],
                    "file_name": row[3],
                    "page_from": row[4],
                    "page_to": row[5],
                    "heading": row[6],
                    "content": content,
                    "score": round(score, 4),
                }
            )
        span.set_attribute("kb.result_count", len(results))
        span.set_attribute("kb.embedding_cache_hit", cache_hit)
        return {
            "results": results,
            "embedding_ms": round((embedded - started) * 1000),
            "query_ms": round((finished - embedded) * 1000),
            "embedding_cache_hit": cache_hit,
        }


def version_kb_ids(config: Mapping[str, Any]) -> set[str]:
    ids = {str(k) for k in config.get("kb_ids") or []}
    ids |= {str(k.get("kb_id")) for k in config.get("knowledge") or [] if isinstance(k, Mapping)}
    return ids
