"""Retrieval accuracy (005 T070, SC-007): for at least 85% of 50 labelled questions the passage
holding the answer is among the results. Runs with the offline embedder, so it guards chunking,
the query path and the threshold; the nightly benchmark repeats it with the real vendor."""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi import FastAPI

from app.knowledge import jobs, service
from app.knowledge.embeddings.fake import FakeEmbeddings
from tests.knowledge_helpers import add_document, deps, new_kb, workspace

QA = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "knowledge" / "qa_set.json").read_text())


def handbook() -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Maple Street Dental handbook", level=1)
    for section in QA["sections"]:
        document.add_heading(section["heading"], level=2)
        document.add_paragraph(section["text"])
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def test_sc007_accuracy(app: FastAPI) -> None:
    actor = await workspace(app)
    kb_id = await new_kb(app, actor, "Handbook")
    doc_id = await add_document(app, actor, kb_id, handbook(), "handbook.docx")
    embedder = FakeEmbeddings()
    assert (await jobs.ingest(deps(app, embedder), doc_id)).status == "ready"
    hits = 0
    misses: list[str] = []
    async with app.state.db.transaction(workspace_id=actor.workspace_id) as session:
        for item in QA["questions"]:
            found = await service.search(session, None, embedder, [kb_id], item["question"], 4)
            if any(item["expect"] in r["content"] for r in found["results"]):
                hits += 1
            else:
                misses.append(item["question"])
    assert hits / len(QA["questions"]) >= 0.85, misses
