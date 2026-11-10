"""Ingestion charge (005 T055, money test-first): embedded tokens x catalog rate x feature
markup, rounded up to $0.000001, posted once per document version and never on failure."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI
from sqlalchemy import select

from app.knowledge import jobs
from app.llms.charges import embedding_cost
from app.llms.client import billable_cost
from app.llms.embeddings.fake import FakeEmbeddings
from app.usage.models import UsageEvent
from tests.fixtures import knowledge as fx
from tests.knowledge_helpers import add_document, deps, document, new_kb, workspace


class PricedFake(FakeEmbeddings):
    provider = "openai"
    model = "text-embedding-3-small"


async def test_cost_formula(app: FastAPI) -> None:
    async with app.state.db.transaction() as session:
        raw = await embedding_cost(session, PricedFake(), 12_345)
    # text-embedding-3-small lists at $0.00002 per 1,000 tokens (001 catalog seed).
    expected_raw = (Decimal(12_345) / 1000 * Decimal("0.000020")).quantize(
        Decimal("0.000001"), rounding="ROUND_CEILING"
    )
    assert raw == expected_raw == Decimal("0.000247")


async def test_charged_once_per_document_version(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    doc_id = await add_document(app, actor, kb_id, fx.refund_policy_pdf())
    embedder = PricedFake()
    assert (await jobs.ingest(deps(app, embedder), doc_id)).status == "ready"
    assert (await jobs.ingest(deps(app, embedder), doc_id)).status == "skipped"
    doc = await document(app, actor, doc_id)
    assert doc is not None and doc.token_count
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        events = list(
            (
                await session.execute(
                    select(UsageEvent).where(UsageEvent.feature_key == "knowledge_ingestion")
                )
            ).scalars()
        )
        raw = await embedding_cost(session, embedder, doc.token_count)
        billable = billable_cost(raw)
    assert len(events) == 1
    event = events[0]
    assert event.quantity == Decimal(doc.token_count) and event.unit == "tokens"
    assert event.raw_cost_usd == raw and event.billable_cost_usd == billable
    assert event.ref_type == "kb_document" and event.ref_id == doc_id


async def test_no_charge_on_failure(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor)
    doc_id = await add_document(app, actor, kb_id, fx.scanned_pdf(), "scan.pdf")
    assert (await jobs.ingest(deps(app, PricedFake()), doc_id)).status == "failed"
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        events = (await session.execute(select(UsageEvent))).scalars().all()
    assert [e for e in events if e.feature_key == "knowledge_ingestion"] == []
