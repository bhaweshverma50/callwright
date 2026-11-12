"""One sync of a Drive source (022 plan "Sync flow"; research R1, R2, R6, R7, R9).

1. Claim the source (row lock, one sync at a time) and record a ``running`` run. A running sync
   refreshes ``running_since`` every minute; one silent for 10 minutes is stale and can be
   taken over. A run that lost its claim stops at its next heartbeat and never touches the
   source's state.
2. Get an access token through the connection. A refused refresh marks the connection revoked
   and its sources ``access_lost``.
3. Check the root, then list the whole tree. Any failure here ends the run with nothing applied:
   lost access or an outage must never look like "every file was deleted".
4. Plan with ``diff.plan``, then apply: skips, renames, adds and real updates (Drive markers,
   then bytes, then extracted text for Google Docs), and finally removals (archived, within the
   mass-archive allowance).
5. Finish the run with its counts and per-file errors, set the source's state and next sync, and
   start ingestion of the new documents after commit.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.connectors import service as connectors
from app.connectors.models import Connection
from app.core.config import Settings
from app.core.db import Database
from app.core.ids import new_id
from app.core.secrets import key_wrapper
from app.core.storage import ObjectStore
from app.knowledge import service as knowledge
from app.knowledge import storage
from app.knowledge.extract import extract_text
from app.knowledge.models import Document, KnowledgeSource, SourceFile, SyncRun
from app.knowledge.sources import diff, guard
from app.knowledge.sources.drive import (
    AccessToken,
    DriveClient,
    DriveItem,
    DriveRoot,
    ExportTooLarge,
    FileUnavailable,
    GoogleTemporary,
    RootUnavailable,
    SourceTooLarge,
    TokenRevoked,
)

log = logging.getLogger(__name__)

MAX_ERRORS = 500
STALE_AFTER = timedelta(minutes=10)
HEARTBEAT_S = 60.0
NO_CREDIT_RETRY = timedelta(minutes=60)
# Per-file temporary Google failures in a row before the run gives up (Google is likely down).
MAX_TEMPORARY_STREAK = 3


class Superseded(Exception):
    """Another sync took the source over after this one missed its heartbeats."""


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SyncDeps:
    db: Database
    redis: Any
    store: ObjectStore
    settings: Settings
    drive: DriveClient
    schedule_ingest: Callable[[list[str]], Awaitable[None]]

    def connector_deps(self) -> connectors.ConnectorDeps:
        return connectors.ConnectorDeps(
            settings=self.settings, redis=self.redis, wrapper=key_wrapper(self.settings), drive=self.drive
        )


@dataclass(frozen=True)
class Claimed:
    run_id: str
    workspace_id: str
    source_id: str
    kb_id: str
    connection_id: str
    root_kind: str
    root_id: str
    drive_id: str | None
    include_subfolders: bool
    interval_minutes: int


@dataclass
class Tally:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    renamed: int = 0
    archived: int = 0
    held_back: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    errors_truncated: int = 0
    attention: str | None = None
    held: dict[str, Any] | None = None
    to_ingest: list[str] = field(default_factory=list)
    beat_at: float = field(default_factory=time.monotonic)
    temporary_streak: int = 0

    def issue(
        self,
        item: DriveItem | SourceFile,
        state: str,
        reason: str,
        message: str | None = None,
        dup: str | None = None,
    ) -> None:
        if state == "skipped":
            self.skipped += 1
        else:
            self.failed += 1
        if len(self.errors) >= MAX_ERRORS:
            self.errors_truncated += 1
            return
        drive_id = item.id if isinstance(item, DriveItem) else item.drive_file_id
        self.errors.append(
            {
                "drive_file_id": drive_id,
                "name": item.name,
                "path": item.path,
                "web_view_link": item.web_view_link,
                "state": state,
                "reason": reason,
                "duplicate_of_doc_id": dup,
                "message": message,
            }
        )


async def workspace_of(db: Database, source_id: str) -> str | None:
    async with db.transaction() as session:
        found = (
            await session.execute(text("SELECT kb_sources_workspace_for(:id)"), {"id": source_id})
        ).scalar_one_or_none()
    return str(found) if found else None


async def has_credit(db: Database, workspace_id: str, source_id: str) -> bool:
    """Scheduled syncs pause while the workspace has no credit (FR-024): the source says why and
    is checked again in an hour. Searches keep working from the synced copy."""
    from app.billing import service as billing

    async with db.transaction(workspace_id=workspace_id) as session:
        if await billing.get_balance(session, workspace_id) > 0:
            src = await session.get(KnowledgeSource, source_id)
            if src is not None and src.attention_reason == "no_credit":
                src.state, src.attention_reason = "healthy", None
            return True
        src = await session.get(KnowledgeSource, source_id)
        if src is not None:
            src.state, src.attention_reason = "needs_attention", "no_credit"
            src.next_sync_at = now() + NO_CREDIT_RETRY
        return False


async def claim(db: Database, workspace_id: str, source_id: str, trigger: str) -> Claimed | None:
    async with db.transaction(workspace_id=workspace_id) as session:
        src = (
            await session.execute(
                select(KnowledgeSource)
                .where(KnowledgeSource.id == source_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if src is None:
            return None
        if src.running_run_id and src.running_since and src.running_since > now() - STALE_AFTER:
            return None
        if src.running_run_id:
            stale = await session.get(SyncRun, src.running_run_id)
            if stale is not None and stale.status == "running":
                stale.status, stale.failure_reason, stale.finished_at = "failed", "internal", now()
        run = SyncRun(id=new_id("ksr"), workspace_id=workspace_id, source_id=source_id, trigger=trigger)
        session.add(run)
        src.running_run_id = run.id
        src.running_since = now()
        if src.state != "needs_attention" or src.attention_reason not in ("mass_archive",):
            src.state = "syncing"
        src.updated_at = now()
        await session.flush()
        return Claimed(
            run_id=run.id,
            workspace_id=workspace_id,
            source_id=src.id,
            kb_id=src.kb_id,
            connection_id=src.connection_id,
            root_kind=src.root_kind,
            root_id=src.root_id,
            drive_id=src.drive_id,
            include_subfolders=src.include_subfolders,
            interval_minutes=src.interval_minutes,
        )


async def claimed_run(db: Database, workspace_id: str, source_id: str, run_id: str) -> Claimed | None:
    async with db.transaction(workspace_id=workspace_id) as session:
        src = await session.get(KnowledgeSource, source_id)
        run = await session.get(SyncRun, run_id)
        if src is None or run is None or run.status != "running" or src.running_run_id != run_id:
            return None
        return Claimed(
            run_id=run.id,
            workspace_id=workspace_id,
            source_id=src.id,
            kb_id=src.kb_id,
            connection_id=src.connection_id,
            root_kind=src.root_kind,
            root_id=src.root_id,
            drive_id=src.drive_id,
            include_subfolders=src.include_subfolders,
            interval_minutes=src.interval_minutes,
        )


async def finish(
    deps: SyncDeps,
    c: Claimed,
    tally: Tally,
    *,
    status: str,
    failure_reason: str | None = None,
    attention: str | None = None,
    root_name: str | None = None,
    next_in: timedelta | None = None,
) -> None:
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        run = await session.get(SyncRun, c.run_id)
        src = await session.get(KnowledgeSource, c.source_id)
        if run is not None:
            run.status = status
            run.failure_reason = failure_reason
            run.finished_at = now()
            for name in (
                "added",
                "updated",
                "unchanged",
                "renamed",
                "archived",
                "held_back",
                "skipped",
                "failed",
            ):
                setattr(run, name, getattr(tally, name))
            run.errors = tally.errors
            run.errors_truncated = tally.errors_truncated
        # Only the run that holds the claim updates the source: a run that was taken over as
        # stale must not clear the new run's claim or overwrite its state.
        if src is not None and src.running_run_id == c.run_id:
            src.running_run_id = None
            src.running_since = None
            src.updated_at = now()
            if root_name:
                src.root_name = root_name
            if status in ("succeeded", "held"):
                src.last_success_at = now()
            reason = attention or tally.attention
            if tally.held is not None:
                src.held_archive = tally.held
                reason = "mass_archive"
            elif status in ("succeeded",) and src.held_archive is not None and reason != "mass_archive":
                src.held_archive = None
            if reason:
                src.state, src.attention_reason = "needs_attention", reason
            elif status == "failed":
                # A temporary failure keeps whatever the source showed before this run.
                src.state = "healthy" if src.last_success_at else "pending"
                src.attention_reason = None
            else:
                src.state, src.attention_reason = "healthy", None
            src.next_sync_at = now() + (next_in or timedelta(minutes=src.interval_minutes))
    if tally.to_ingest:
        await deps.schedule_ingest(tally.to_ingest)


async def run_sync(deps: SyncDeps, source_id: str, trigger: str, run_id: str | None = None) -> str | None:
    """Run one sync. ``run_id`` continues a run a request already claimed (Sync now, first sync).
    Returns the run id, or None when another sync holds the source."""
    workspace_id = await workspace_of(deps.db, source_id)
    if workspace_id is None:
        return None
    if trigger == "scheduled" and not await has_credit(deps.db, workspace_id, source_id):
        return None
    c = (
        await claimed_run(deps.db, workspace_id, source_id, run_id)
        if run_id
        else await claim(deps.db, workspace_id, source_id, trigger)
    )
    if c is None:
        return None
    tally = Tally()
    try:
        await _sync(deps, c, tally)
    except Superseded:
        log.warning("sync %s of source %s was taken over as stale", c.run_id, c.source_id)
        await finish(deps, c, tally, status="failed", failure_reason="internal")
    except asyncio.CancelledError:
        # The job timed out or the worker is stopping: record the run as failed (what it applied
        # is kept) and release the claim, then let the cancellation through.
        log.warning("sync %s of source %s was cancelled", c.run_id, c.source_id)
        await asyncio.shield(finish(deps, c, tally, status="failed", failure_reason="internal"))
        raise
    except Exception:
        log.exception("sync %s of source %s crashed", c.run_id, c.source_id)
        await finish(deps, c, tally, status="failed", failure_reason="internal")
    return c.run_id


async def heartbeat(deps: SyncDeps, c: Claimed, tally: Tally, *, force: bool = False) -> None:
    """Keep the claim fresh during a long sync. Raises :class:`Superseded` when the source is no
    longer claimed by this run."""
    moment = time.monotonic()
    if not force and moment - tally.beat_at < HEARTBEAT_S:
        return
    tally.beat_at = moment
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        src = await session.get(KnowledgeSource, c.source_id, with_for_update=True)
        if src is None or src.running_run_id != c.run_id:
            raise Superseded
        src.running_since = now()


async def _token(deps: SyncDeps, c: Claimed) -> AccessToken | str:
    """An access token, or the failure reason when there is none."""
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        conn = await session.get(Connection, c.connection_id)
        if conn is None or conn.health == "revoked":
            return "connection_revoked"
        try:
            return await connectors.access_token(session, deps.connector_deps(), conn)
        except TokenRevoked:
            return "connection_revoked"
        except GoogleTemporary:
            return "google_unavailable"


async def _mark_revoked(deps: SyncDeps, c: Claimed) -> None:
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        conn = await session.get(Connection, c.connection_id)
        if conn is not None:
            await connectors.mark_revoked(session, conn)


async def _sync(deps: SyncDeps, c: Claimed, tally: Tally) -> None:
    token = await _token(deps, c)
    if isinstance(token, str):
        reason = token
        attention = "access_lost" if reason == "connection_revoked" else None
        await finish(deps, c, tally, status="failed", failure_reason=reason, attention=attention)
        return
    try:
        root = await deps.drive.get_root(token, c.root_kind, c.root_id, c.drive_id)  # type: ignore[arg-type]
        listing = await deps.drive.list_tree(token, root, c.include_subfolders)
    except TokenRevoked:
        await _mark_revoked(deps, c)
        await finish(
            deps, c, tally, status="failed", failure_reason="connection_revoked", attention="access_lost"
        )
        return
    except RootUnavailable:
        await finish(deps, c, tally, status="failed", failure_reason="access_lost", attention="access_lost")
        return
    except SourceTooLarge:
        await finish(
            deps, c, tally, status="failed", failure_reason="source_too_large", attention="source_too_large"
        )
        return
    except GoogleTemporary:
        await finish(deps, c, tally, status="failed", failure_reason="google_unavailable")
        return
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        known = list(
            (await session.execute(select(SourceFile).where(SourceFile.source_id == c.source_id))).scalars()
        )
        for row in known:
            session.expunge(row)
    plan = diff.plan(listing, known)
    try:
        await _apply(deps, c, tally, token, root, plan)
    except TokenRevoked:
        await _mark_revoked(deps, c)
        await finish(
            deps, c, tally, status="failed", failure_reason="connection_revoked", attention="access_lost"
        )
        return
    except GoogleTemporary:
        # Adds and updates already applied are safe; nothing was archived (removals run last).
        await finish(deps, c, tally, status="failed", failure_reason="google_unavailable")
        return
    await finish(deps, c, tally, status="held" if tally.held else "succeeded", root_name=root.name)


async def _fetch(deps: SyncDeps, token: AccessToken, item: DriveItem) -> bytes:
    if item.is_google_doc:
        return await deps.drive.export_docx(token, item.id)
    return await deps.drive.download(token, item.id)


def text_hash(data: bytes, file_type: str = "docx") -> str | None:
    """SHA-256 of the normalised extracted text, so a re-exported Google Doc with the same words
    is not processed (and charged) again (research R2). None when the file cannot be read."""
    try:
        words = extract_text(data, file_type)
    except Exception:
        return None
    return hashlib.sha256(words.encode()).hexdigest()


def _markers(row: SourceFile, item: DriveItem) -> None:
    row.name = item.name
    row.path = item.path
    row.mime_type = item.mime_type
    row.web_view_link = item.web_view_link
    row.drive_version = item.version
    row.md5 = item.md5
    row.size_bytes = item.size
    row.updated_at = now()


async def _file_row(session: AsyncSession, c: Claimed, item: DriveItem) -> SourceFile:
    row = (
        await session.execute(
            select(SourceFile).where(SourceFile.source_id == c.source_id, SourceFile.drive_file_id == item.id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = SourceFile(
            id=str(ULID()),
            workspace_id=c.workspace_id,
            source_id=c.source_id,
            drive_file_id=item.id,
            name=item.name,
            path=item.path,
            mime_type=item.mime_type,
            state="skipped",
        )
        session.add(row)
    row.last_seen_run_id = c.run_id
    return row


async def _revive(session: AsyncSession, row: SourceFile, tally: Tally) -> None:
    """A listed file is synced again: kept after a restore, or back after being removed (its
    archived document returns to search without processing, or is processed when it was archived
    before it ever was)."""
    if row.state in ("kept", "removed"):
        row.state = "synced"
    for doc_id in (row.doc_id, row.pending_doc_id):
        doc = await session.get(Document, doc_id) if doc_id else None
        if doc is not None and doc.status == "archived" and knowledge.unarchive(doc):
            tally.to_ingest.append(doc.id)


async def _record_skip(
    deps: SyncDeps, c: Claimed, tally: Tally, item: DriveItem, reason: str, **kw: Any
) -> None:
    state = "failed" if reason in ("download_failed", "processing_failed") else "skipped"
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        row = await _file_row(session, c, item)
        if row.doc_id is None:
            _markers(row, item)
            row.state = state
        # else: an imported file whose new version could not be taken keeps the markers of the
        # version it serves, so the next sync tries the new version again.
        row.reason = reason
        row.message = kw.get("message")
        row.duplicate_of_doc_id = kw.get("dup")
    tally.issue(item, state, reason, kw.get("message"), kw.get("dup"))
    if reason in ("kb_full", "workspace_storage_full"):
        tally.attention = "kb_full"


async def _apply(
    deps: SyncDeps, c: Claimed, tally: Tally, token: AccessToken, root: DriveRoot, plan: diff.SyncPlan
) -> None:
    for item, reason in plan.skips:
        await _record_skip(deps, c, tally, item, reason)
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        if plan.forgotten:
            await session.execute(delete(SourceFile).where(SourceFile.id.in_([f.id for f in plan.forgotten])))
        for known in plan.unchanged:
            row = await session.get(SourceFile, known.id)
            if row is not None:
                row.last_seen_run_id = c.run_id
                await _revive(session, row, tally)
        for item, known in plan.renames:
            row = await session.get(SourceFile, known.id)
            if row is None:
                continue
            _markers(row, item)
            row.last_seen_run_id = c.run_id
            await _revive(session, row, tally)
            if row.doc_id:
                doc = await session.get(Document, row.doc_id)
                if doc is not None:
                    doc.display_name = item.name[:255]
    tally.unchanged += len(plan.unchanged)
    tally.renamed += len(plan.renames)
    for item in plan.adds:
        await heartbeat(deps, c, tally)
        await _add(deps, c, tally, token, item)
    for item, known in plan.updates:
        await heartbeat(deps, c, tally)
        await _update(deps, c, tally, token, item, known)
    await heartbeat(deps, c, tally, force=True)
    await _remove(deps, c, tally, plan.removals)


async def _download(
    deps: SyncDeps, c: Claimed, tally: Tally, token: AccessToken, item: DriveItem
) -> bytes | None:
    """The file's bytes, or None after recording why this one file was not taken. Only revoked
    access, or several temporary Google failures in a row, end the whole run."""
    try:
        data = await _fetch(deps, token, item)
    except ExportTooLarge as exc:
        await _record_skip(deps, c, tally, item, "export_too_large", message=exc.message)
    except FileUnavailable as exc:
        await _record_skip(deps, c, tally, item, "download_failed", message=exc.message)
    except (GoogleTemporary, httpx.HTTPError) as exc:
        tally.temporary_streak += 1
        if tally.temporary_streak >= MAX_TEMPORARY_STREAK:
            raise GoogleTemporary("Google failed several downloads in a row") from exc
        message = getattr(exc, "message", "") or "Google did not answer. It is tried again next sync."
        await _record_skip(deps, c, tally, item, "download_failed", message=message)
    else:
        tally.temporary_streak = 0
        return data
    return None


async def _add(deps: SyncDeps, c: Claimed, tally: Tally, token: AccessToken, item: DriveItem) -> None:
    data = await _download(deps, c, tally, token, item)
    if data is None:
        return
    texts = text_hash(data) if item.is_google_doc else None
    skip: tuple[str, str | None] | None = None
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        result = await knowledge.intake(
            session,
            deps.store,
            workspace_id=c.workspace_id,
            kb_id=c.kb_id,
            data=data,
            file_name=item.name,
            source_id=c.source_id,
        )
        if result.outcome == "duplicate" and result.duplicate_of is not None:
            moved = await _relink(session, c, tally, item, result.duplicate_of)
            if moved is not None:
                _markers(moved, item)
                moved.sha256, moved.text_sha256 = result.duplicate_of.sha256, texts
                tally.renamed += 1
                return
        if result.outcome != "created" or result.doc is None:
            dup = result.duplicate_of.id if result.duplicate_of is not None else None
            skip = ({"empty": "download_failed"}.get(result.outcome, result.outcome), dup)
        else:
            row = await _file_row(session, c, item)
            _markers(row, item)
            row.state, row.reason, row.message, row.duplicate_of_doc_id = "synced", None, None, None
            row.doc_id = result.doc.id
            row.sha256, row.text_sha256 = result.doc.sha256, texts
    if skip is not None:
        await _record_skip(deps, c, tally, item, skip[0], dup=skip[1])
        return
    assert result.doc is not None
    tally.added += 1
    tally.to_ingest.append(result.doc.id)


async def _relink(
    session: AsyncSession, c: Claimed, tally: Tally, item: DriveItem, doc: Document
) -> SourceFile | None:
    """A file whose content matches a document that already left its old place in this knowledge
    base (archived, or its file removed from a source) is a move, not a duplicate (analyze F1).
    The document is linked to this file and restored when archived; it is never processed again."""
    previous = (
        await session.execute(select(SourceFile).where(SourceFile.doc_id == doc.id))
    ).scalar_one_or_none()
    if doc.status != "archived" and (previous is None or previous.state != "removed"):
        return None
    if previous is not None:
        previous.doc_id = None
    row = await _file_row(session, c, item)
    row.state, row.reason, row.message, row.duplicate_of_doc_id = "synced", None, None, None
    row.doc_id = doc.id
    doc.source_id = c.source_id
    doc.display_name = item.name[:255]
    if doc.status == "archived" and knowledge.unarchive(doc):
        tally.to_ingest.append(doc.id)
    await session.flush()
    return row


async def _hand_over(session: AsyncSession, c: Claimed, doc_id: str) -> bool:
    """Before archiving a removed file's document, give it to a file in the same knowledge base
    that was skipped as its duplicate: the file moved to another source, which synced first."""
    waiting = (
        await session.execute(
            select(SourceFile)
            .join(KnowledgeSource, KnowledgeSource.id == SourceFile.source_id)
            .where(
                KnowledgeSource.kb_id == c.kb_id,
                SourceFile.reason == "duplicate",
                SourceFile.duplicate_of_doc_id == doc_id,
                SourceFile.doc_id.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if waiting is None:
        return False
    waiting.state, waiting.reason, waiting.duplicate_of_doc_id = "synced", None, None
    waiting.doc_id = doc_id
    doc = await session.get(Document, doc_id)
    if doc is not None:
        doc.source_id = waiting.source_id
        doc.display_name = waiting.name[:255]
    return True


async def _update(
    deps: SyncDeps, c: Claimed, tally: Tally, token: AccessToken, item: DriveItem, known: SourceFile
) -> None:
    """A file whose markers moved. ``row.sha256`` and ``row.text_sha256`` describe the newest
    version taken in: the pending one (``pending_doc_id``) while it is processed, otherwise the
    served one (``doc_id``). Ingestion moves ``doc_id`` to the pending version when it is ready."""
    data = await _download(deps, c, tally, token, item)
    if data is None:
        return
    sha = hashlib.sha256(data).hexdigest()
    texts = text_hash(data) if item.is_google_doc else None
    same = sha == known.sha256 or (texts is not None and texts == known.text_sha256)
    dropped: list[str] = []
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        row = await session.get(SourceFile, known.id)
        if row is None:
            return
        renamed = item.name != row.name or item.path != row.path
        pending = await session.get(Document, row.pending_doc_id) if row.pending_doc_id else None
        newest = pending or (await session.get(Document, row.doc_id) if row.doc_id else None)
        if same and newest is not None and newest.status == "failed":
            # Same content as the version that failed processing: process it again.
            await knowledge.reprocess(session, newest.kb_id, newest.id)
            _markers(row, item)
            row.last_seen_run_id = c.run_id
            row.reason = row.message = None
            if row.state == "failed":
                row.state = "synced"
            tally.updated += 1
            tally.to_ingest.append(newest.id)
            return
        if same:
            _markers(row, item)
            row.last_seen_run_id = c.run_id
            await _revive(session, row, tally)
            if renamed:
                for doc in (newest, pending):
                    if doc is not None:
                        doc.display_name = item.name[:255]
                tally.renamed += 1
            else:
                tally.unchanged += 1
            return
        if pending is not None:
            # A newer edit replaces a version that is still processing or failed: drop it.
            dropped.append(pending.storage_key)
            await session.delete(pending)
            row.pending_doc_id = None
            await session.flush()
        result = await knowledge.intake(
            session,
            deps.store,
            workspace_id=c.workspace_id,
            kb_id=c.kb_id,
            data=data,
            file_name=item.name,
            source_id=c.source_id,
            replace_doc_id=row.doc_id,
        )
        if result.outcome != "created" or result.doc is None:
            # Not taken: the markers stay on the served version so the next sync tries again.
            dup = result.duplicate_of.id if result.duplicate_of is not None else None
            row.last_seen_run_id = c.run_id
            row.reason, row.duplicate_of_doc_id = result.outcome, dup
            tally.issue(item, "skipped", result.outcome, None, dup)
            if result.outcome in ("kb_full", "workspace_storage_full"):
                tally.attention = "kb_full"
            return
        _markers(row, item)
        row.last_seen_run_id = c.run_id
        row.state = "synced"
        row.pending_doc_id = result.doc.id
        row.sha256, row.text_sha256 = result.doc.sha256, texts
        row.reason = row.message = None
    for key in dropped:
        with contextlib.suppress(Exception):
            await storage.delete(deps.store, key)
    tally.updated += 1
    tally.to_ingest.append(result.doc.id)


async def _remove(deps: SyncDeps, c: Claimed, tally: Tally, removals: list[SourceFile]) -> None:
    if not removals:
        return
    async with deps.db.transaction(workspace_id=c.workspace_id) as session:
        to_archive: list[SourceFile] = []
        for f in removals:
            row = await session.get(SourceFile, f.id)
            if row is None or row.doc_id is None:
                continue
            if await _hand_over(session, c, row.doc_id):
                row.doc_id, row.state = None, "removed"
                tally.renamed += 1
            else:
                to_archive.append(row)
        if not to_archive:
            return
        active = await guard.active_documents(session, c.source_id)
        decision = guard.decide([r.doc_id for r in to_archive if r.doc_id], active)
        if isinstance(decision, guard.Hold):
            tally.held_back = len(decision.doc_ids)
            tally.held = {
                "doc_ids": decision.doc_ids,
                "would_archive": decision.would_archive,
                "of": decision.of,
                "run_id": c.run_id,
            }
            return
        tally.archived += await knowledge.archive_documents(session, decision.doc_ids)
        # A new version still processing leaves search with the file (it stays archived when
        # its processing finishes).
        await knowledge.archive_documents(session, [r.pending_doc_id for r in to_archive if r.pending_doc_id])
        for row in to_archive:
            row.state = "removed"
