"""Ingestion end to end with the fake embedder (005 T056)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.knowledge import jobs
from app.knowledge.embeddings.fake import FakeEmbeddings
from app.knowledge.models import Chunk, Document
from tests.fixtures import knowledge as fx
from tests.knowledge_helpers import add_document, deps, document, new_kb, workspace


async def chunk_count(app: FastAPI, workspace_id: str, doc_id: str) -> int:
    async with app.state.db.transaction(workspace_id=workspace_id) as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc_id))
            ).scalar_one()
        )


async def test_upload_to_ready_and_retry_is_idempotent(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    doc_id = await add_document(app, actor, kb_id, fx.policies_docx(), "policies.docx")
    assert (await jobs.ingest(deps(app), doc_id)).status == "ready"
    first = await chunk_count(app, actor.workspace_id, doc_id)
    doc = await document(app, actor, doc_id)
    assert doc is not None and doc.status == "ready" and doc.chunk_count == first > 0
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        row = await session.get(Document, doc_id)
        assert row is not None
        row.status = "uploaded"  # a redelivered job
    assert (await jobs.ingest(deps(app), doc_id)).status == "ready"
    assert await chunk_count(app, actor.workspace_id, doc_id) == first, "no duplicate chunks"


async def test_transient_failures_back_off_then_fail(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    doc_id = await add_document(app, actor, kb_id, fx.refund_policy_pdf())
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    outcome = await jobs.run_inline(deps(app, FakeEmbeddings(fail_times=10)), doc_id, sleep=fake_sleep)
    assert outcome.status == "failed" and sleeps == [10.0, 60.0, 300.0]
    doc = await document(app, actor, doc_id)
    assert doc is not None and doc.error_code == "embedding_unavailable"


async def test_transient_failure_then_success(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    doc_id = await add_document(app, actor, kb_id, fx.refund_policy_pdf())

    async def no_sleep(seconds: float) -> None:
        return None

    outcome = await jobs.run_inline(deps(app, FakeEmbeddings(fail_times=1)), doc_id, sleep=no_sleep)
    assert outcome.status == "ready"


async def test_replace_swaps_after_ready(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    old_id = await add_document(app, actor, kb_id, fx.policies_docx(), "policies.docx")
    await jobs.ingest(deps(app), old_id)
    new_id = await add_document(
        app, actor, kb_id, fx.policies_docx("Updated in October."), "policies.docx", replace_doc_id=old_id
    )
    assert await document(app, actor, old_id) is not None, "old stays until the new one is ready"
    assert (await jobs.ingest(deps(app), new_id)).status == "ready"
    assert await document(app, actor, old_id) is None
    assert await chunk_count(app, actor.workspace_id, old_id) == 0
    new = await document(app, actor, new_id)
    assert new is not None and new.status == "ready"
    assert all(not key.endswith(new.sha256 + ".docx") or new_id in key for key in app.state.storage.objects)


async def test_two_ingestions_per_workspace(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    docs = [
        await add_document(app, actor, kb_id, fx.policies_docx(f"Copy {i}."), f"p{i}.docx") for i in range(3)
    ]
    embedder = FakeEmbeddings(latency_s=0.2)
    outcomes = await asyncio.gather(*(jobs.ingest(deps(app, embedder), d) for d in docs))
    statuses = sorted(o.status for o in outcomes)
    assert statuses == ["busy", "ready", "ready"]
    busy = docs[[o.status for o in outcomes].index("busy")]
    assert (await jobs.ingest(deps(app, embedder), busy)).status == "ready"
