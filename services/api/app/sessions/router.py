"""POST /v1/sessions/web-call (contracts/sessions.yaml, 003 T031, T052).

Refusals map to problems with the refused call's id: 402 ``insufficient_credit``, 403
``email_unverified``, 409 ``agent_not_published`` and ``flow_not_compiled``, 422 ``unsupported_vendor``,
``pricing_unavailable`` and ``flow_runtime_unavailable``, 429 ``concurrency_limit``. The whole
response, success or problem, is replayed for a repeated ``Idempotency-Key``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.core import idempotency
from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.sessions.schemas import WebCallRequest, WebCallSession
from app.sessions.service import WebCallDeps, start_web_call

router = APIRouter(tags=["sessions"])

ENDPOINT = "POST /v1/sessions/web-call"


def deps_from(request: Request) -> WebCallDeps:
    state = request.app.state
    return WebCallDeps(
        db=state.db,
        settings=state.settings,
        livekit=state.livekit,
        catalog=state.adapter_catalog,
        jobs=getattr(state, "jobs", None),
    )


@router.post(
    "/sessions/web-call",
    status_code=201,
    response_model=WebCallSession,
    responses=problem_responses(400, 401, 402, 403, 404, 409, 422, 429, 503),
)
async def create_web_call(
    body: WebCallRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = idempotency.require_key(idempotency_key)
    deps = deps_from(request)

    async def handler() -> tuple[int, Any]:
        return 201, await start_web_call(deps, principal, body)

    return await idempotency.run_idempotent(
        deps.db,
        workspace_id=principal.workspace_id,
        endpoint=ENDPOINT,
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )
