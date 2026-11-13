"""/v1/knowledge-bases/{kb_id}/sources and document restore and archive
(specs/022-knowledge-connectors/contracts/connectors.yaml; T045, T061, T064, T077, T084)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.connectors.router import deps as connector_deps
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import ProblemError, problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.knowledge import jobs as ingest_jobs
from app.knowledge import service as knowledge
from app.knowledge.models import Document, SourceFile, SyncRun
from app.knowledge.router import DocId, KbId
from app.knowledge.sources import jobs, service
from app.knowledge.sources.schemas import SourceCreate, SourceUpdate

router = APIRouter(tags=["knowledge"])

SourceId = Annotated[str, Depends(path_id("ksrc", "knowledge source", "source_id"))]
SOURCE = "/knowledge-bases/{kb_id}/sources/{source_id}"


@router.get("/knowledge-bases/{kb_id}/sources", responses=problem_responses(401, 404))
async def list_sources(kb_id: KbId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return {"items": await service.views(session, await service.list_sources(session, kb_id))}


@router.post(
    "/knowledge-bases/{kb_id}/sources",
    status_code=201,
    responses=problem_responses(401, 402, 404, 409, 422, 503),
)
async def create_source(
    kb_id: KbId, body: SourceCreate, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    d = connector_deps(request)
    from app.connectors.service import ensure_enabled

    ensure_enabled(d.settings, principal.workspace_id)
    await _require_credit(request, principal.workspace_id)
    async with principal_tx(request, principal) as session:
        src = await service.create(
            session, d, workspace_id=principal.workspace_id, user_id=principal.user_id, kb_id=kb_id, body=body
        )
        source_id = src.id
    claimed = await service.start_sync(request.app.state.db, principal.workspace_id, source_id, "first")
    if claimed is not None:
        await jobs.schedule(request.app.state, source_id, "first", claimed.run_id)
    async with principal_tx(request, principal) as session:
        [view] = await service.views(session, [await service.get_source(session, kb_id, source_id)])
    return JSONResponse(view, status_code=201)


@router.get(SOURCE, responses=problem_responses(401, 404))
async def get_source(
    kb_id: KbId, source_id: SourceId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await service.detail(session, await service.get_source(session, kb_id, source_id))


@router.patch(SOURCE, responses=problem_responses(401, 404, 422))
async def update_source(
    kb_id: KbId, source_id: SourceId, body: SourceUpdate, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        src = await service.update_source(session, await service.get_source(session, kb_id, source_id), body)
        [view] = await service.views(session, [src])
        return view


@router.delete(SOURCE, status_code=204, responses=problem_responses(401, 404, 409, 422))
async def delete_source(
    kb_id: KbId,
    source_id: SourceId,
    request: Request,
    principal: CurrentPrincipal,
    documents: Annotated[Literal["keep", "archive"], Query()],
) -> Response:
    async with principal_tx(request, principal) as session:
        src = await service.get_source(session, kb_id, source_id)
        await service.remove(session, src, documents=documents, user_id=principal.user_id)
    return Response(status_code=204)


async def _require_credit(request: Request, workspace_id: str) -> None:
    from app.billing import service as billing

    async with request.app.state.db.transaction(workspace_id=workspace_id) as session:
        if await billing.get_balance(session, workspace_id) <= 0:
            raise billing.insufficient_credit()


@router.post(f"{SOURCE}/sync", status_code=202, responses=problem_responses(401, 402, 404, 409, 503))
async def sync_source(
    kb_id: KbId, source_id: SourceId, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    from app.connectors.models import Connection
    from app.connectors.service import ensure_configured, revoked_problem

    ensure_configured(request.app.state.settings)
    await _require_credit(request, principal.workspace_id)
    async with principal_tx(request, principal) as session:
        src = await service.get_source(session, kb_id, source_id)
        if service.is_running(src):
            raise service.sync_running(await service.running_run(session, src))
        conn = await session.get(Connection, src.connection_id)
        if conn is None or conn.health == "revoked":
            raise revoked_problem()
    claimed = await service.start_sync(request.app.state.db, principal.workspace_id, source_id, "manual")
    async with principal_tx(request, principal) as session:
        if claimed is None:
            src = await service.get_source(session, kb_id, source_id)
            raise service.sync_running(await service.running_run(session, src))
        run = await session.get(SyncRun, claimed.run_id)
        assert run is not None
        body = service.run_view(run)
    await jobs.schedule(request.app.state, source_id, "manual", claimed.run_id)
    return JSONResponse(body, status_code=202)


@router.post(f"{SOURCE}/held-archive/{{decision}}", responses=problem_responses(401, 404, 409))
async def decide_held_archive(
    kb_id: KbId,
    source_id: SourceId,
    decision: Literal["confirm", "cancel"],
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        src = await service.get_source(session, kb_id, source_id)
        src = await service.decide_held(session, src, decision, principal.user_id)
        [view] = await service.views(session, [src])
        return view


@router.get(f"{SOURCE}/runs", responses=problem_responses(401, 404))
async def list_runs(
    kb_id: KbId,
    source_id: SourceId,
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        src = await service.get_source(session, kb_id, source_id)
        rows, total = await service.list_runs(session, src, page, page_size)
    return {"items": [service.run_view(r) for r in rows], **page_meta(total, page, page_size)}


@router.get(f"{SOURCE}/runs/{{run_id}}", responses=problem_responses(401, 404))
async def get_run(
    kb_id: KbId, source_id: SourceId, run_id: str, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        src = await service.get_source(session, kb_id, source_id)
        return service.run_detail(await service.get_run(session, src, run_id))


async def _doc_response(session: Any, doc: Document) -> dict[str, Any]:
    [view] = await knowledge.document_views(session, [doc])
    return view


@router.post(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/restore", responses=problem_responses(401, 404, 409)
)
async def restore_document(
    kb_id: KbId, doc_id: DocId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Back into search at once, with no processing (FR-013), when the document had been
    processed; one archived before it was processed is processed now, and one that had failed
    comes back as failed. A synced document whose file is still missing is kept: later syncs
    leave it alone until its file returns."""
    async with principal_tx(request, principal) as session:
        doc = await knowledge.get_document(session, kb_id, doc_id)
        if doc.status != "archived":
            raise ProblemError(
                409, "not_archived", "Not archived", "Only archived documents can be restored."
            )
        needs_ingest = knowledge.unarchive(doc)
        row = (
            await session.execute(select(SourceFile).where(SourceFile.doc_id == doc.id))
        ).scalar_one_or_none()
        if row is not None and row.state == "removed":
            row.state = "kept"
        await session.flush()
        response = await _doc_response(session, doc)
    if needs_ingest:
        await ingest_jobs.schedule(request.app.state, doc_id)
    return response


@router.post(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/archive", responses=problem_responses(401, 404, 409)
)
async def archive_document(
    kb_id: KbId, doc_id: DocId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Archive a synced document kept after a restore while its Drive file is still missing."""
    async with principal_tx(request, principal) as session:
        doc = await knowledge.get_document(session, kb_id, doc_id)
        row = (
            await session.execute(select(SourceFile).where(SourceFile.doc_id == doc.id))
        ).scalar_one_or_none()
        if row is None or row.state != "kept" or doc.status == "archived":
            raise ProblemError(
                409,
                "not_kept",
                "Cannot archive",
                "Only synced documents kept after a restore, whose file is missing, can be archived here.",
            )
        await knowledge.archive_documents(session, [doc.id])
        row.state = "removed"
        await session.flush()
        await session.refresh(doc)
        return await _doc_response(session, doc)
