"""Knowledge bases (005); registers the ``kb_ids`` validator and ``knowledge`` snapshot resolver
with 002, and runs document ingestion."""

from __future__ import annotations

from arq.cron import cron

from app.core.feature import Feature, Runtime
from app.knowledge import hooks
from app.knowledge.jobs import JOB_NAME, ingest_document
from app.knowledge.router import internal_router, router
from app.knowledge.sources import jobs as sync_jobs
from app.knowledge.sources.router import router as sources_router


def install(runtime: Runtime) -> None:
    hooks.register()


FEATURE = Feature(
    "knowledge",
    routers=(router, sources_router, internal_router),
    install=install,
    jobs={
        JOB_NAME: ingest_document,
        sync_jobs.JOB_NAME: sync_jobs.sync_source,
        "sync_due": sync_jobs.sync_due,
        "purge_knowledge_sources": sync_jobs.purge,
    },
    job_timeouts={sync_jobs.JOB_NAME: sync_jobs.JOB_TIMEOUT_S},
    crons=(
        cron(sync_jobs.sync_due, second={10}, run_at_startup=False, unique=True),
        cron(sync_jobs.purge, hour={4}, minute={45}, run_at_startup=False),
    ),
    id_prefixes=frozenset({"kb", "doc", "ksrc", "ksr"}),
)
