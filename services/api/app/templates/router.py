"""/v1/templates (contracts/templates.yaml; T074)."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query, Request

from app.core.auth import CurrentPrincipal
from app.core.errors import not_found, problem_responses
from app.templates import service

router = APIRouter(tags=["templates"])
SLUG = re.compile(r"^[a-z0-9-]{3,64}$")
Category = Literal["automotive", "banking", "ecommerce", "healthcare", "telecom"]


@router.get("/templates", responses=problem_responses(401))
async def list_templates(
    request: Request,
    principal: CurrentPrincipal,
    category: Annotated[Category | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        rows = await service.list_templates(session, category=category, search=search)
    return {"items": [service.summary_json(t) for t in rows]}


@router.get("/templates/categories", responses=problem_responses(401))
async def list_template_categories(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return {"items": await service.categories(session)}


@router.get("/templates/{template_id}", responses=problem_responses(401, 404))
async def get_template(
    request: Request, principal: CurrentPrincipal, template_id: Annotated[str, Path(max_length=100)]
) -> dict[str, Any]:
    if not SLUG.match(template_id):
        raise not_found("template")
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        template = await service.get_template(session, template_id)
    if template is None:
        raise not_found("template")
    return service.detail_json(template)
