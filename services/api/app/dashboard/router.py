"""``/v1/dashboard/stats``, ``/quality`` and ``/agent-health`` (006 T046, contracts/dashboard.yaml)."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import problem_responses
from app.dashboard import service
from app.dashboard.periods import Window, resolve_period, zone

router = APIRouter(tags=["dashboard"])
_AGENT = re.compile(r"^agt_[A-Za-z0-9]+$")

PeriodParam = Annotated[str | None, Query(alias="period")]
DateParam = Annotated[str | None, Query()]
AgentIdsParam = Annotated[str | None, Query()]
TzParam = Annotated[str, Query()]


def _agents(raw: str | None) -> list[str]:
    return list(dict.fromkeys(a.strip() for a in (raw or "").split(",") if _AGENT.match(a.strip())))


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


async def _window(
    session: Any, period: str | None, start: str | None, end: str | None, tz: str, agents: list[str]
) -> Window:
    first = None
    if period == "all_time":
        first = await service.first_call_day(session, zone(tz).key, agents)
    return resolve_period(period, start, end, tz, first_call_day=first)


@router.get("/dashboard/stats", responses=problem_responses(401, 422))
async def dashboard_stats(
    request: Request,
    principal: CurrentPrincipal,
    period: PeriodParam = None,
    start_date: DateParam = None,
    end_date: DateParam = None,
    agent_ids: AgentIdsParam = None,
    tz: TzParam = "UTC",
) -> dict[str, Any]:
    agents = _agents(agent_ids)
    async with _tx(request, principal) as session:
        window = await _window(session, period, start_date, end_date, tz, agents)
        return await service.stats(session, window, agents)


@router.get("/dashboard/quality", responses=problem_responses(401, 422))
async def dashboard_quality(
    request: Request,
    principal: CurrentPrincipal,
    period: PeriodParam = None,
    start_date: DateParam = None,
    end_date: DateParam = None,
    agent_ids: AgentIdsParam = None,
    tz: TzParam = "UTC",
    compare: bool = True,
) -> dict[str, Any]:
    agents = _agents(agent_ids)
    async with _tx(request, principal) as session:
        window = await _window(session, period, start_date, end_date, tz, agents)
        return await service.quality(session, window, agents, compare)


@router.get("/dashboard/agent-health", responses=problem_responses(401))
async def dashboard_agent_health(
    request: Request,
    principal: CurrentPrincipal,
    agent_ids: AgentIdsParam = None,
    tz: TzParam = "UTC",
) -> dict[str, Any]:
    agents = _agents(agent_ids)
    window = resolve_period("last_30_days", None, None, tz)
    async with _tx(request, principal) as session:
        return await service.agent_health(session, window, agents)
