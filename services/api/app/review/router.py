"""/v1 review queue (007 T066; contracts/review.yaml)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request

from app.core.auth import CurrentPrincipal
from app.core.errors import field_error, problem_responses, validation_failed
from app.core.ids import is_valid_id
from app.review import service

router = APIRouter(tags=["review"])
Lookback = Annotated[int, Query(ge=1, le=90)]


def _check_agent(agent_id: str | None) -> None:
    if agent_id and not is_valid_id(agent_id, "agt"):
        raise validation_failed([field_error("/agent_id", "invalid_format", "Pick an agent from the list")])


@router.get("/review/queue", responses=problem_responses(422))
async def get_queue(
    request: Request,
    principal: CurrentPrincipal,
    strategy: Annotated[Literal["random", "failed", "disagreement"], Query()] = "disagreement",
    agent_id: Annotated[str | None, Query()] = None,
    lookback_days: Lookback = 30,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    _check_agent(agent_id)
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        items = await service.queue(
            session,
            user_id=principal.user_id,
            strategy=strategy,
            agent_id=agent_id,
            lookback_days=lookback_days,
            limit=limit,
        )
    return {"strategy": strategy, "items": items}


@router.get("/review/queue/summary")
async def get_summary(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: Annotated[str | None, Query()] = None,
    lookback_days: Lookback = 30,
) -> dict[str, int]:
    _check_agent(agent_id)
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        return await service.summary(
            session, user_id=principal.user_id, agent_id=agent_id, lookback_days=lookback_days
        )
