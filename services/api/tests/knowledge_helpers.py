"""Helpers for knowledge tests (005): direct uploads and ingestion with a fake embedder."""

from __future__ import annotations

from fastapi import FastAPI

from app.agents.service import Actor
from app.knowledge import jobs, service
from app.knowledge.models import Document
from app.llms.embeddings.fake import FakeEmbeddings
from tests.conftest import make_workspace


async def workspace(app: FastAPI) -> Actor:
    user_id, workspace_id = await make_workspace(app)
    return Actor(workspace_id=workspace_id, user_id=user_id)


def deps(app: FastAPI, embedder: FakeEmbeddings | None = None) -> jobs.IngestDeps:
    return jobs.IngestDeps(
        db=app.state.db, redis=app.state.redis, store=app.state.storage, embedder=embedder or FakeEmbeddings()
    )


async def new_kb(app: FastAPI, actor: Actor, name: str = "Policies") -> str:
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        kb = await service.create_kb(session, actor, name, "Clinic policies")
        return kb.id


async def add_document(
    app: FastAPI,
    actor: Actor,
    kb_id: str,
    data: bytes,
    name: str = "doc.pdf",
    replace_doc_id: str | None = None,
) -> str:
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        doc = await service.create_document(
            session,
            actor,
            app.state.storage,
            kb_id,
            service.Upload(
                file_name=name, data=data, replace_doc_id=replace_doc_id, acknowledge_duplicate=True
            ),
        )
        return doc.id


async def document(app: FastAPI, actor: Actor, doc_id: str) -> Document | None:
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        doc = await session.get(Document, doc_id)
        if doc is not None:
            session.expunge(doc)
        return doc
