"""Homepage playground: visitors call a demo agent from the browser without an account.

``GET /v1/public/demo`` lists the scenario keys that are switched on. It never touches Redis, so
a page view does not wake the realtime VM. ``POST /v1/public/demo-calls`` starts a browser call
to the published version of that scenario's agent in the demo workspace through 003's
``start_web_call``. Each visitor IP gets ``DEMO_CALLS_PER_HOUR`` calls; that Redis read is also
what wakes a sleeping VM (503 ``waking_up``, which the page retries). Calls are charged to the
demo workspace, so its balance caps total spend, and each agent's maximum duration caps a call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.client_ip import client_ip
from app.core.errors import ProblemError, problem_responses, too_many_requests
from app.core.rate_limit import TokenBucket
from app.sessions.router import deps_from
from app.sessions.schemas import WebCallRequest, WebCallSession
from app.sessions.service import start_web_call

router = APIRouter(tags=["demo"])


class DemoInfo(BaseModel):
    agents: list[str]


class DemoCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")


@dataclass(frozen=True)
class DemoCaller:
    workspace_id: str
    user_id: str | None = None


@router.get("/public/demo", response_model=DemoInfo)
async def demo_info(request: Request) -> DemoInfo:
    return DemoInfo(agents=list(request.app.state.settings.demo_agent_ids))


@router.post(
    "/public/demo-calls",
    status_code=201,
    response_model=WebCallSession,
    responses=problem_responses(402, 404, 409, 422, 429, 503),
)
async def start_demo_call(body: DemoCallRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    agent_id = settings.demo_agent_ids.get(body.agent)
    if agent_id is None:
        raise ProblemError(404, "not_found", "Not found", "This demo agent is not available.")
    per_hour = settings.demo_calls_per_hour
    bucket = TokenBucket(request.app.state.redis, rate_per_s=per_hour / 3600, burst=per_hour)
    limited = await bucket.take("demo", client_ip(request))
    if not limited.allowed:
        raise too_many_requests(
            limited.retry_after_s,
            f"That is {per_hour} demo calls this hour. Create an account to keep calling.",
        )
    request_body = WebCallRequest(
        agent_id=agent_id, version="published", metadata={"source": "homepage_playground"}
    )
    return await start_web_call(
        deps_from(request), DemoCaller(workspace_id=settings.demo_workspace_id), request_body
    )
