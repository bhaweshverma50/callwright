"""Knowledge sources (022 US2 to US5): add, view, change and remove Drive sources, Sync now,
held-archive decisions and run history. The sync itself is ``sync.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import activity
from app.connectors import service as connectors
from app.connectors.models import Connection
from app.core.db import Database
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.core.pagination import page_window
from app.knowledge import service as knowledge
from app.knowledge.models import Document, KnowledgeSource, SourceFile, SyncRun
from app.knowledge.sources import guard, sync
from app.knowledge.sources.drive import GoogleTemporary, RootUnavailable, TokenRevoked
from app.knowledge.sources.schemas import SourceCreate, SourceUpdate

COUNT_FIELDS = ("added", "updated", "unchanged", "renamed", "archived", "held_back", "skipped", "failed")
ATTENTION_MESSAGES = {
    "access_lost": "Access to this folder was lost. Reconnect the Google account or share the folder again.",
    "kb_full": "The knowledge base is full, so some files were not imported.",
    "no_credit": "Out of credit, so scheduled syncs are paused. Searches keep working.",
    "source_too_large": "The folder holds more than 5,000 items. Pick a narrower folder.",
}


def now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def sync_running(run: dict[str, Any] | None) -> ProblemError:
    return ProblemError(
        409,
        "sync_running",
        "Sync in progress",
        "A sync of this source is running. Wait for it to finish.",
        extra={"run": run} if run else None,
    )


def run_view(run: SyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "source_id": run.source_id,
        "trigger": run.trigger,
        "status": run.status,
        "failure_reason": run.failure_reason,
        "started_at": run.started_at.isoformat(),
        "finished_at": _iso(run.finished_at),
        "counts": {name: getattr(run, name) or 0 for name in COUNT_FIELDS},
    }


def run_detail(run: SyncRun) -> dict[str, Any]:
    return {**run_view(run), "errors": list(run.errors or []), "errors_truncated": run.errors_truncated or 0}


def attention_message(src: KnowledgeSource) -> str | None:
    if src.state != "needs_attention" or not src.attention_reason:
        return None
    if src.attention_reason == "mass_archive" and src.held_archive:
        return guard.message(int(src.held_archive["would_archive"]), int(src.held_archive["of"]))
    return ATTENTION_MESSAGES.get(src.attention_reason)


async def views(session: AsyncSession, sources: list[KnowledgeSource]) -> list[dict[str, Any]]:
    if not sources:
        return []
    ids = [s.id for s in sources]
    emails = dict(
        (
            await session.execute(
                select(Connection.id, Connection.account_email).where(
                    Connection.id.in_({s.connection_id for s in sources})
                )
            )
        ).all()
    )
    counts = dict(
        (
            await session.execute(
                select(Document.source_id, func.count())
                .where(Document.source_id.in_(ids), Document.status != "archived")
                .group_by(Document.source_id)
            )
        ).all()
    )
    latest: dict[str, SyncRun] = {}
    for run in (
        await session.execute(
            select(SyncRun)
            .where(SyncRun.source_id.in_(ids))
            .distinct(SyncRun.source_id)
            .order_by(SyncRun.source_id, SyncRun.started_at.desc())
        )
    ).scalars():
        latest[run.source_id] = run
    return [
        {
            "id": s.id,
            "kb_id": s.kb_id,
            "connection_id": s.connection_id,
            "account_email": emails.get(s.connection_id, ""),
            "kind": s.kind,
            "root_kind": s.root_kind,
            "root_id": s.root_id,
            "root_name": s.root_name,
            "include_subfolders": s.include_subfolders,
            "interval_minutes": s.interval_minutes,
            "state": s.state,
            "attention_reason": s.attention_reason if s.state == "needs_attention" else None,
            "attention_message": attention_message(s),
            "held_archive": (
                {"would_archive": s.held_archive["would_archive"], "of": s.held_archive["of"]}
                if s.held_archive
                else None
            ),
            "document_count": int(counts.get(s.id, 0)),
            "last_success_at": _iso(s.last_success_at),
            "next_sync_at": _iso(s.next_sync_at),
            "last_run": run_view(latest[s.id]) if s.id in latest else None,
            "created_at": s.created_at.isoformat(),
        }
        for s in sources
    ]


async def detail(session: AsyncSession, src: KnowledgeSource) -> dict[str, Any]:
    [view] = await views(session, [src])
    files = (
        await session.execute(
            select(SourceFile)
            .where(
                SourceFile.source_id == src.id, SourceFile.reason.is_not(None), SourceFile.doc_id.is_(None)
            )
            .order_by(SourceFile.path, SourceFile.name)
            .limit(500)
        )
    ).scalars()
    view["not_imported"] = [
        {
            "drive_file_id": f.drive_file_id,
            "name": f.name,
            "path": f.path,
            "web_view_link": f.web_view_link,
            "state": "failed" if f.state == "failed" else "skipped",
            "reason": f.reason,
            "duplicate_of_doc_id": f.duplicate_of_doc_id,
            "message": f.message,
        }
        for f in files
    ]
    return view


async def list_sources(session: AsyncSession, kb_id: str) -> list[KnowledgeSource]:
    await knowledge.get_kb(session, kb_id)
    rows = await session.execute(
        select(KnowledgeSource).where(KnowledgeSource.kb_id == kb_id).order_by(KnowledgeSource.created_at)
    )
    return list(rows.scalars())


async def get_source(session: AsyncSession, kb_id: str, source_id: str) -> KnowledgeSource:
    await knowledge.get_kb(session, kb_id)
    src = await session.get(KnowledgeSource, source_id) if is_valid_id(source_id, "ksrc") else None
    if src is None or src.kb_id != kb_id:
        raise not_found("knowledge source")
    return src


async def create(
    session: AsyncSession,
    deps: connectors.ConnectorDeps,
    *,
    workspace_id: str,
    user_id: str,
    kb_id: str,
    body: SourceCreate,
) -> KnowledgeSource:
    await knowledge.get_kb(session, kb_id)
    conn = await session.get(Connection, body.connection_id)
    if conn is None:
        raise validation_failed(
            [field_error("/connection_id", "not_found", "No connection with that id exists.")]
        )
    if conn.health == "revoked":
        raise connectors.revoked_problem()
    exists = (
        await session.execute(
            select(KnowledgeSource.id).where(
                KnowledgeSource.kb_id == kb_id, KnowledgeSource.root_id == body.root_id
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise ProblemError(
            409,
            "source_exists",
            "Already a source",
            "This folder is already a source of this knowledge base.",
        )
    try:
        token = await connectors.access_token(session, deps, conn)
        root = await deps.drive.get_root(token, body.root_kind, body.root_id, body.drive_id)
    except TokenRevoked as exc:
        raise connectors.revoked_problem() from exc
    except RootUnavailable as exc:
        raise validation_failed(
            [field_error("/root_id", "unreadable", "This Google account cannot read that folder.")]
        ) from exc
    except GoogleTemporary as exc:
        raise ProblemError(
            503, "google_unavailable", "Google unavailable", "Google did not answer. Try again in a minute."
        ) from exc
    src = KnowledgeSource(
        id=new_id("ksrc"),
        workspace_id=workspace_id,
        kb_id=kb_id,
        connection_id=conn.id,
        kind="google_drive",
        root_kind=body.root_kind,
        root_id=body.root_id,
        drive_id=root.drive_id or body.drive_id,
        root_name=root.name,
        include_subfolders=True if body.root_kind == "shared_drive" else body.include_subfolders,
        interval_minutes=body.interval_minutes,
        state="pending",
        created_by=user_id,
    )
    session.add(src)
    await session.flush()
    await activity.record(
        session,
        workspace_id=workspace_id,
        action="source_added",
        subject_type="source",
        subject_id=src.id,
        actor_user_id=user_id,
        detail={"kb_id": kb_id, "root_name": root.name, "connection_id": conn.id},
    )
    await session.refresh(src)
    return src


async def update_source(session: AsyncSession, src: KnowledgeSource, body: SourceUpdate) -> KnowledgeSource:
    if body.include_subfolders is not None and src.root_kind == "folder":
        src.include_subfolders = body.include_subfolders
    if body.interval_minutes is not None:
        src.interval_minutes = body.interval_minutes
        if src.next_sync_at is not None:
            src.next_sync_at = (src.last_success_at or now()) + timedelta(minutes=src.interval_minutes)
    src.updated_at = now()
    await session.flush()
    return src


def is_running(src: KnowledgeSource) -> bool:
    return bool(src.running_run_id and src.running_since and src.running_since > now() - sync.STALE_AFTER)


async def running_run(session: AsyncSession, src: KnowledgeSource) -> dict[str, Any] | None:
    run = await session.get(SyncRun, src.running_run_id) if src.running_run_id else None
    return run_view(run) if run is not None else None


async def remove(session: AsyncSession, src: KnowledgeSource, *, documents: str, user_id: str) -> None:
    """FR-018: remove a source, keeping its documents as uploads or archiving them."""
    if is_running(src):
        raise sync_running(await running_run(session, src))
    doc_ids = list((await session.execute(select(Document.id).where(Document.source_id == src.id))).scalars())
    if documents == "archive":
        await knowledge.archive_documents(session, doc_ids)
    if doc_ids:
        for doc in (await session.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars():
            doc.source_id = None
    await activity.record(
        session,
        workspace_id=src.workspace_id,
        action="source_removed",
        subject_type="source",
        subject_id=src.id,
        actor_user_id=user_id,
        detail={"kb_id": src.kb_id, "root_name": src.root_name, "documents": documents},
    )
    await session.delete(src)
    await session.flush()


async def start_sync(db: Database, workspace_id: str, source_id: str, trigger: str) -> sync.Claimed | None:
    return await sync.claim(db, workspace_id, source_id, trigger)


async def decide_held(
    session: AsyncSession, src: KnowledgeSource, decision: str, user_id: str
) -> KnowledgeSource:
    """Confirm or cancel archiving a sync held back (FR-014). Confirm archives only the held
    documents whose files are still missing; documents whose files came back are left alone."""
    held = src.held_archive
    if not held:
        raise ProblemError(409, "nothing_held", "Nothing held", "No archiving is waiting for a decision.")
    if decision == "confirm":
        held_run = str(held.get("run_id", ""))
        rows = list(
            (
                await session.execute(
                    select(SourceFile).where(
                        SourceFile.source_id == src.id, SourceFile.doc_id.in_(held["doc_ids"])
                    )
                )
            ).scalars()
        )
        still_missing = [r for r in rows if not (r.last_seen_run_id and r.last_seen_run_id >= held_run)]
        await knowledge.archive_documents(session, [r.doc_id for r in still_missing if r.doc_id])
        for row in still_missing:
            row.state = "removed"
    src.held_archive = None
    src.state, src.attention_reason = "healthy", None
    src.updated_at = now()
    await activity.record(
        session,
        workspace_id=src.workspace_id,
        action="held_archive_confirmed" if decision == "confirm" else "held_archive_cancelled",
        subject_type="source",
        subject_id=src.id,
        actor_user_id=user_id,
        detail={"would_archive": held.get("would_archive"), "of": held.get("of")},
    )
    await session.flush()
    return src


async def list_runs(
    session: AsyncSession, src: KnowledgeSource, page: int, page_size: int
) -> tuple[list[SyncRun], int]:
    query = select(SyncRun).where(SyncRun.source_id == src.id)
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = await session.execute(
        query.order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).slice(*page_window(page, page_size))
    )
    return list(rows.scalars()), total


async def get_run(session: AsyncSession, src: KnowledgeSource, run_id: str) -> SyncRun:
    run = await session.get(SyncRun, run_id) if is_valid_id(run_id, "ksr") else None
    if run is None or run.source_id != src.id:
        raise not_found("sync run")
    return run
