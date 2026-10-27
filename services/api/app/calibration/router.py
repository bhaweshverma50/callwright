"""/v1 calibration (007 T053; contracts/calibration.yaml)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request

from app.calibration import service
from app.core.auth import CurrentPrincipal
from app.core.errors import field_error, validation_failed
from app.core.ids import is_valid_id

router = APIRouter(tags=["calibration"])
Lookback = Annotated[int, Query(ge=1, le=365)]


def _check_agent(agent_id: str | None) -> None:
    if agent_id and not is_valid_id(agent_id, "agt"):
        raise validation_failed([field_error("/agent_id", "invalid_format", "Pick an agent from the list")])


@router.get("/calibration/evaluators")
async def list_rows(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: Annotated[str | None, Query()] = None,
    lookback_days: Lookback = 90,
    version_scope: Annotated[Literal["current", "all"], Query()] = "current",
) -> dict[str, Any]:
    _check_agent(agent_id)
    minimum = int(request.app.state.settings.calibration_min_sample)
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        items = await service.rows(
            session,
            agent_id=agent_id,
            lookback_days=lookback_days,
            version_scope=version_scope,
            min_sample=minimum,
        )
    return {"min_sample_for_signal": minimum, "items": items}


@router.get("/calibration/summary")
async def get_summary(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: Annotated[str | None, Query()] = None,
    lookback_days: Lookback = 90,
) -> dict[str, int]:
    _check_agent(agent_id)
    minimum = int(request.app.state.settings.calibration_min_sample)
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        return await service.summary(
            session, agent_id=agent_id, lookback_days=lookback_days, min_sample=minimum
        )
