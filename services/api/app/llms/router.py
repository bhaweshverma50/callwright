"""/v1/llms/catalog (contracts/llms.yaml; T034)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.llms import service
from app.pricing import service as pricing_service

router = APIRouter(tags=["llms"])


@router.get("/llms/catalog", responses=problem_responses(401))
async def get_llm_catalog(
    request: Request,
    principal: CurrentPrincipal,
    include_withdrawn: Annotated[bool, Query()] = False,
) -> JSONResponse:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        pricing = await pricing_service.catalog_now(session)
    body = service.catalog_json(pricing, include_withdrawn=include_withdrawn)
    return JSONResponse(body, headers={"Cache-Control": "private, max-age=300"})
