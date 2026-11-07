"""/v1/knowledge-bases, /v1/agents/{agent_id}/knowledge-bases and the internal search
(specs/005-tools-knowledge/contracts/knowledge.yaml; T065, T076)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.calls.lookups import config_for, workspace_for_call
from app.calls.models import Call
from app.core.auth import CurrentPrincipal, Principal, require_service
from app.core.errors import forbidden, not_found, problem_responses, too_many_requests
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.core.rate_limit import RateLimiter
from app.knowledge import jobs, service, storage
from app.knowledge.schemas import (
    CheckDuplicate,
    InternalSearch,
    KnowledgeBaseWrite,
    SearchRequest,
    SetAgentKnowledge,
)
from app.tools.router import AgentId

router = APIRouter(tags=["knowledge"])
internal_router = APIRouter(tags=["internal"], dependencies=[Depends(require_service)])

KbId = Annotated[str, Depends(path_id("kb", "knowledge base", "kb_id"))]
DocId = Annotated[str, Depends(path_id("doc", "document", "doc_id"))]
PREVIEW_SEARCHES_PER_MINUTE = 60
READ_CHUNK = 1024 * 1024
DocumentStatus = Annotated[str | None, Query(pattern="^(uploaded|processing|ready|failed)$")]


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


def _actor(principal: Principal) -> service.KnowledgeActor:
    return service.KnowledgeActor(workspace_id=principal.workspace_id, user_id=principal.user_id)


async def _kb_body(session: Any, kb: Any) -> dict[str, Any]:
    [view] = await service.kb_views(session, [kb])
    return view


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    request: Request,
    principal: CurrentPrincipal,
    search: Annotated[str | None, Query(max_length=120)] = None,
    attachable: Annotated[bool | None, Query()] = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_kbs(
            session, search=search, attachable=attachable, page=page, page_size=page_size
        )
        items = await service.kb_views(session, rows)
    return {"items": items, **page_meta(total, page, page_size)}


@router.post("/knowledge-bases", status_code=201, responses=problem_responses(409, 422))
async def create_knowledge_base(
    body: KnowledgeBaseWrite, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        kb = await service.create_kb(session, _actor(principal), body.name or "", body.description or "")
        return await _kb_body(session, kb)


@router.get("/knowledge-bases/{kb_id}", responses=problem_responses(404))
async def get_knowledge_base(kb_id: KbId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        return await _kb_body(session, await service.get_kb(session, kb_id))


@router.patch("/knowledge-bases/{kb_id}", responses=problem_responses(404, 409, 422))
async def update_knowledge_base(
    kb_id: KbId, body: KnowledgeBaseWrite, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        kb = await service.update_kb(session, kb_id, body.name, body.description)
        return await _kb_body(session, kb)


@router.delete("/knowledge-bases/{kb_id}", responses=problem_responses(404, 409))
async def delete_knowledge_base(
    kb_id: KbId,
    request: Request,
    principal: CurrentPrincipal,
    confirm: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        detached = await service.delete_kb(
            session, _actor(principal), request.app.state.storage, kb_id, confirm=confirm
        )
    return {"deleted": True, "detached_agent_ids": detached}


@router.get("/knowledge-bases/{kb_id}/documents", responses=problem_responses(404))
async def list_documents(
    kb_id: KbId,
    request: Request,
    principal: CurrentPrincipal,
    status: DocumentStatus = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_documents(
            session, kb_id, status=status, page=page, page_size=page_size
        )
    return {"items": [service.document_view(d) for d in rows], **page_meta(total, page, page_size)}


async def _read_capped(upload: UploadFile) -> bytes:
    data = bytearray()
    while chunk := await upload.read(READ_CHUNK):
        data.extend(chunk)
        if len(data) > service.MAX_FILE_BYTES:
            raise service.file_too_large()
    return bytes(data)


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    status_code=202,
    responses=problem_responses(404, 409, 413, 415, 422),
)
async def upload_document(
    kb_id: KbId,
    request: Request,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    display_name: Annotated[str | None, Form(min_length=1, max_length=255)] = None,
    replace_doc_id: Annotated[str | None, Form(pattern="^doc_")] = None,
    acknowledge_duplicate: Annotated[bool, Form()] = False,
) -> JSONResponse:
    data = await _read_capped(file)
    upload = service.Upload(
        file_name=file.filename or "document",
        data=data,
        display_name=display_name,
        replace_doc_id=replace_doc_id,
        acknowledge_duplicate=acknowledge_duplicate,
    )
    async with _tx(request, principal) as session:
        doc = await service.create_document(
            session, _actor(principal), request.app.state.storage, kb_id, upload
        )
        body = service.document_view(doc)
    await jobs.schedule(request.app.state, doc.id)
    return JSONResponse(body, status_code=202)


@router.post("/knowledge-bases/{kb_id}/documents/check-duplicate", responses=problem_responses(404))
async def check_duplicate_document(
    kb_id: KbId, body: CheckDuplicate, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        await service.get_kb(session, kb_id)
        verdict, matches = await service.duplicate_matches(session, kb_id, body.file_name, body.sha256)
    return {"verdict": verdict, "matches": [m.__dict__ for m in matches]}


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}", responses=problem_responses(404))
async def get_document(
    kb_id: KbId, doc_id: DocId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        return service.document_view(await service.get_document(session, kb_id, doc_id))


@router.delete(
    "/knowledge-bases/{kb_id}/documents/{doc_id}", status_code=204, responses=problem_responses(404)
)
async def delete_document(
    kb_id: KbId, doc_id: DocId, request: Request, principal: CurrentPrincipal
) -> Response:
    async with _tx(request, principal) as session:
        await service.delete_document(session, request.app.state.storage, kb_id, doc_id)
    return Response(status_code=204)


@router.post(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/reprocess",
    status_code=202,
    responses=problem_responses(404, 409),
)
async def reprocess_document(
    kb_id: KbId, doc_id: DocId, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    async with _tx(request, principal) as session:
        doc = await service.reprocess(session, kb_id, doc_id)
        body = service.document_view(doc)
    await jobs.schedule(request.app.state, doc_id)
    return JSONResponse(body, status_code=202)


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/url", responses=problem_responses(404))
async def get_document_url(
    kb_id: KbId, doc_id: DocId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        doc = await service.get_document(session, kb_id, doc_id)
        key = doc.storage_key
    url, expires_at = await storage.signed_url(request.app.state.storage, key)
    return {"url": url, "expires_at": expires_at.isoformat()}


@router.post("/knowledge-bases/{kb_id}/search", responses=problem_responses(404, 429))
async def preview_search(
    kb_id: KbId, body: SearchRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    state = request.app.state
    limit = await RateLimiter(state.redis).hit(
        "kb_preview_search", principal.workspace_id, limit=PREVIEW_SEARCHES_PER_MINUTE, window_s=60
    )
    if not limit.allowed:
        raise too_many_requests(limit.retry_after_s, "Preview searches are limited to 60 a minute.")
    deps = jobs.deps_from_state(state)
    async with _tx(request, principal) as session:
        await service.get_kb(session, kb_id)
        return await service.search(session, state.redis, deps.embedder, [kb_id], body.query, body.top_k)


async def _agent_set(session: Any, agent_id: str, kbs: list[Any]) -> dict[str, Any]:
    return {"agent_id": agent_id, "knowledge_bases": await service.kb_views(session, kbs)}


@router.get("/agents/{agent_id}/knowledge-bases", responses=problem_responses(404))
async def get_agent_knowledge_bases(
    agent_id: AgentId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        return await _agent_set(session, agent_id, await service.agent_kbs(session, agent_id))


@router.put("/agents/{agent_id}/knowledge-bases", responses=problem_responses(404, 422))
async def set_agent_knowledge_bases(
    agent_id: AgentId, body: SetAgentKnowledge, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        kbs = await service.set_agent_kbs(session, _actor(principal), agent_id, body.kb_ids)
        return await _agent_set(session, agent_id, kbs)


@internal_router.post("/internal/knowledge/search", responses=problem_responses(403, 404))
async def internal_knowledge_search(body: InternalSearch, request: Request) -> dict[str, Any]:
    """Workspace from the call; ``kb_ids`` must belong to the call's agent version (R15).

    008: a simulated call searches the knowledge of the snapshot it runs (variants included),
    and a single-turn test case (no call) passes its test run id instead of a call id."""
    state = request.app.state
    deps = jobs.deps_from_state(state)
    if body.call_id.startswith("trn_"):
        from app.test_runs.router import run_workspace
        from app.test_runs.service import get_run

        workspace_id = await run_workspace(request, body.call_id)
        async with state.db.transaction(workspace_id=workspace_id) as session:
            run = await get_run(session, body.call_id)
            if not set(body.kb_ids) <= service.version_kb_ids(run.config_snapshot):
                raise forbidden("These knowledge bases are not attached to the tested configuration.")
            return await service.search(
                session, state.redis, deps.embedder, body.kb_ids, body.query, body.top_k
            )
    workspace_id = await workspace_for_call(state.db, body.call_id)
    async with state.db.transaction(workspace_id=workspace_id) as session:
        call = await session.get(Call, body.call_id)
        if call is None:
            raise not_found("call")
        config = await config_for(session, call)
        allowed = service.version_kb_ids(config) if config is not None else set()
        if not set(body.kb_ids) <= allowed:
            raise forbidden("These knowledge bases are not attached to the call's agent version.")
        return await service.search(session, state.redis, deps.embedder, body.kb_ids, body.query, body.top_k)
