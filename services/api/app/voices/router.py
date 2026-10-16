"""/v1/voices (contracts/voices.yaml; T037, T104)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Path, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.agents.checks import pricing_now
from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import problem_responses
from app.voices import catalog, service
from app.voices.adapters.base import VoiceFilters

router = APIRouter(tags=["voices"])


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


@router.get("/voices/catalog", responses=problem_responses(401))
async def get_voice_catalog(
    request: Request, principal: CurrentPrincipal, include_withdrawn: Annotated[bool, Query()] = False
) -> JSONResponse:
    async with _tx(request, principal) as session:
        pricing = await pricing_now(session)
    body = catalog.catalog_json(pricing, include_withdrawn=include_withdrawn)
    return JSONResponse(body, headers={"Cache-Control": "private, max-age=300"})


@router.get("/voices/ambient-audio", responses=problem_responses(401))
async def list_ambient_audio(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    store = request.app.state.storage
    async with _tx(request, principal) as session:
        rows = await service.list_ambient(session, principal.workspace_id)
    return {"items": [await service.ambient_json(store, row) for row in rows]}


@router.post(
    "/voices/ambient-audio",
    status_code=201,
    responses={
        **problem_responses(401, 409),
        413: {"description": "File too large"},
        415: {"description": "Unsupported media type"},
    },
)
async def upload_ambient_audio(
    request: Request, principal: CurrentPrincipal, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    if len(data) > service.MAX_UPLOAD_BYTES:
        raise service.too_large()
    store = request.app.state.storage
    async with _tx(request, principal) as session:
        row = await service.upload_ambient(
            session,
            store,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            filename=file.filename or "audio",
            data=data,
        )
    return await service.ambient_json(store, row)


@router.delete("/voices/ambient-audio", status_code=204, responses=problem_responses(404, 409))
async def delete_ambient_audio(
    request: Request, principal: CurrentPrincipal, key: Annotated[str, Query(max_length=300)]
) -> Response:
    async with _tx(request, principal) as session:
        await service.delete_ambient(session, request.app.state.storage, principal.workspace_id, key)
    return Response(status_code=204)


@router.get(
    "/voices/{provider}/voices",
    responses={**problem_responses(401, 404), 503: {"description": "Provider listing unavailable"}},
)
async def list_provider_voices(
    request: Request,
    principal: CurrentPrincipal,
    provider: Annotated[str, Path(max_length=64)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    gender: Annotated[Literal["female", "male", "neutral"] | None, Query()] = None,
    language: Annotated[str | None, Query(max_length=16)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    page = await service.list_voices(
        request.app.state.redis,
        request.app.state.settings,
        provider,
        VoiceFilters(search=search, gender=gender, language=language, model=model),
        cursor,
        limit,
    )
    return page.json()
