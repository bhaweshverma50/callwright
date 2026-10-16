"""/v1/usage (contracts/usage.yaml)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.usage import service
from app.usage.schemas import report_json

router = APIRouter(tags=["usage"])


@router.get("/usage", responses=problem_responses(401, 422))
async def get_usage(
    request: Request,
    principal: CurrentPrincipal,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    db = request.app.state.db
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        report = await service.report(session, principal.workspace_id, from_, to)
    return report_json(report)
