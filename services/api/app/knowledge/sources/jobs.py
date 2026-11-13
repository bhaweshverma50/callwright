"""Running syncs (022 T043, T063; research R10).

* ``schedule(state, source_id, trigger)``: after a request commits (first sync, Sync now). With
  in-memory storage (tests, local demos without S3) the sync runs as a task in this process;
  otherwise the arq job ``sync_source`` is enqueued. Each enqueue has its own job id: arq keeps
  finished job ids for an hour, and the source row lock already allows one sync at a time.
* ``sync_due`` (cron, every minute): enqueues every due source and claims its next due time at
  once, so a source still waiting in the queue is not enqueued again a minute later.
* ``purge`` (cron, daily): archived documents after 30 days, sync runs after 90 days.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from ulid import ULID

from app.core.db import Database
from app.knowledge import jobs as ingest_jobs
from app.knowledge import storage
from app.knowledge.models import Document, KnowledgeSource, SourceFile, SyncRun
from app.knowledge.sources import drive_client
from app.knowledge.sources.sync import SyncDeps, run_sync

log = logging.getLogger(__name__)

JOB_NAME = "sync_source"
# A long first sync gets 25 minutes per job (arq's default is 5). A run cut off here is finished
# as failed with everything applied so far kept; the next sync carries on from there.
JOB_TIMEOUT_S = 25 * 60
DUE_LIMIT = 100
ARCHIVE_DAYS = 30
RUN_DAYS = 90

_inline: set[asyncio.Task[Any]] = set()


def deps_from_state(state: Any) -> SyncDeps:
    async def schedule_ingest(doc_ids: list[str]) -> None:
        for doc_id in doc_ids:
            await ingest_jobs.schedule(state, doc_id)

    return SyncDeps(
        db=state.db,
        redis=state.redis,
        store=state.storage,
        settings=state.settings,
        drive=drive_client(),
        schedule_ingest=schedule_ingest,
    )


def deps_from_ctx(ctx: dict[str, Any]) -> SyncDeps:
    async def schedule_ingest(doc_ids: list[str]) -> None:
        for doc_id in doc_ids:
            await ctx["jobs"].enqueue(
                ingest_jobs.JOB_NAME, doc_id, job_id=f"{ingest_jobs.JOB_NAME}:{doc_id}:{ULID()}"
            )

    return SyncDeps(
        db=ctx["db"],
        redis=ctx.get("redis"),
        store=ctx["store"],
        settings=ctx["settings"],
        drive=drive_client(),
        schedule_ingest=schedule_ingest,
    )


async def run_now(state: Any, source_id: str, trigger: str, run_id: str | None = None) -> str | None:
    return await run_sync(deps_from_state(state), source_id, trigger, run_id)


async def schedule(state: Any, source_id: str, trigger: str, run_id: str | None = None) -> None:
    """Run the sync (continuing ``run_id`` when the request already claimed the source)."""
    if storage.is_in_memory(state.storage):
        task = asyncio.create_task(run_now(state, source_id, trigger, run_id))
        _inline.add(task)
        task.add_done_callback(_inline.discard)
        return
    await state.jobs.enqueue(JOB_NAME, source_id, trigger, run_id, job_id=f"kb_sync:{source_id}:{ULID()}")


async def drain() -> None:
    """Wait for in-process syncs (tests, shutdown)."""
    while _inline:
        await asyncio.gather(*list(_inline), return_exceptions=True)


async def sync_source(
    ctx: dict[str, Any], source_id: str, trigger: str = "scheduled", run_id: str | None = None
) -> str:
    """arq job: one sync of one source."""
    done = await run_sync(deps_from_ctx(ctx), source_id, trigger, run_id)
    return done or "busy"


async def due_sources(db: Database, limit: int = DUE_LIMIT) -> list[tuple[str, str]]:
    """Claim due sources: their next sync moves forward by their interval as they are returned."""
    async with db.transaction() as session:
        rows = (
            await session.execute(
                text("SELECT id, workspace_id FROM kb_sources_due(:now, :limit)"),
                {"now": datetime.now(UTC), "limit": limit},
            )
        ).all()
    claimed: list[tuple[str, str]] = []
    for source_id, workspace_id in rows:
        async with db.transaction(workspace_id=str(workspace_id)) as session:
            src = await session.get(KnowledgeSource, str(source_id))
            if src is None:
                continue
            src.next_sync_at = datetime.now(UTC) + timedelta(minutes=src.interval_minutes)
        claimed.append((str(source_id), str(workspace_id)))
    return claimed


PAUSE_KEY = "connectors:sync_paused"


async def scheduling_paused(settings: Any, redis: Any) -> bool:
    """The kill switch: ``CONNECTORS_SYNC_PAUSED`` or the Redis key ``connectors:sync_paused``
    (set and cleared with redis-cli, no redeploy). Due sources stay due and run once resumed."""
    if getattr(settings, "connectors_sync_paused", False):
        return True
    if redis is None:
        return False
    try:
        return bool(await redis.get(PAUSE_KEY))
    except Exception:  # Redis down: the scheduler cannot enqueue anyway
        return False


async def sync_due(ctx: dict[str, Any]) -> int:
    """Cron: enqueue every due source (research R10), unless scheduling is paused."""
    if await scheduling_paused(ctx.get("settings"), ctx.get("redis")):
        log.warning("scheduled Drive syncs are paused (kill switch)")
        return 0
    claimed = await due_sources(ctx["db"])
    for source_id, _ in claimed:
        await ctx["jobs"].enqueue(JOB_NAME, source_id, "scheduled", job_id=f"kb_sync:{source_id}:{ULID()}")
    return len(claimed)


async def purge_archived(db: Database, store: Any, before: datetime | None = None) -> int:
    """Delete documents archived more than 30 days ago (FR-013), with their chunks and files."""
    before = before or datetime.now(UTC) - timedelta(days=ARCHIVE_DAYS)
    async with db.transaction() as session:
        rows = (
            await session.execute(
                text("SELECT id, workspace_id FROM kb_documents_archived_before(:before, 500)"),
                {"before": before},
            )
        ).all()
    deleted = 0
    for doc_id, workspace_id in rows:
        key: str | None = None
        async with db.transaction(workspace_id=str(workspace_id)) as session:
            doc = await session.get(Document, str(doc_id))
            if doc is None or doc.status != "archived":
                continue
            key = doc.storage_key
            await session.execute(update(SourceFile).where(SourceFile.doc_id == doc.id).values(doc_id=None))
            await session.delete(doc)
            deleted += 1
        if key:
            with contextlib.suppress(Exception):
                await storage.delete(store, key)
    return deleted


async def purge_runs(db: Database, before: datetime | None = None) -> int:
    """Delete sync runs older than 90 days (FR-022)."""
    before = before or datetime.now(UTC) - timedelta(days=RUN_DAYS)
    async with db.transaction() as session:
        rows = (
            await session.execute(
                text("SELECT id, workspace_id FROM kb_sync_runs_before(:before, 5000)"), {"before": before}
            )
        ).all()
    by_workspace: dict[str, list[str]] = {}
    for run_id, workspace_id in rows:
        by_workspace.setdefault(str(workspace_id), []).append(str(run_id))
    for workspace_id, ids in by_workspace.items():
        async with db.transaction(workspace_id=workspace_id) as session:
            for run in (await session.execute(select(SyncRun).where(SyncRun.id.in_(ids)))).scalars():
                await session.delete(run)
    return sum(len(v) for v in by_workspace.values())


async def purge(ctx: dict[str, Any]) -> str:
    """Cron: the daily clean-up of archived documents and old sync runs."""
    documents = await purge_archived(ctx["db"], ctx["store"])
    runs = await purge_runs(ctx["db"])
    return f"{documents} documents, {runs} runs"
