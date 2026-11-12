"""Knowledge bases (005); registers the ``kb_ids`` validator and ``knowledge`` snapshot resolver
with 002, and runs document ingestion."""

from __future__ import annotations

from app.core.feature import Feature, Runtime
from app.knowledge import hooks
from app.knowledge.jobs import JOB_NAME, ingest_document
from app.knowledge.router import internal_router, router


def install(runtime: Runtime) -> None:
    hooks.register()


FEATURE = Feature(
    "knowledge",
    routers=(router, internal_router),
    install=install,
    jobs={JOB_NAME: ingest_document},
    id_prefixes=frozenset({"kb", "doc", "ksrc", "ksr"}),
)
