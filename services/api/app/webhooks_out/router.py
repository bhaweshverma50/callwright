"""/v1/webhooks: signing secret, delivery log, redeliver, test event (contracts/webhooks_out.yaml,
003 T092)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.calls.effects import Deferred, dispatch
from app.core.auth import CurrentPrincipal
from app.core.errors import ProblemError, not_found, problem_responses
from app.core.ids import new_id, path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.core.secrets import key_wrapper
from app.webhooks_out import jobs, service
from app.webhooks_out.models import DELIVERY_STATUSES, WEBHOOK_EVENTS, WebhookDelivery

router = APIRouter(tags=["webhooks"])

DeliveryId = Annotated[str, Depends(path_id("whd", "webhook delivery", "delivery_id"))]
LOG_DAYS = 30


class TestRequest(BaseModel):
    url: str = Field(max_length=2048)
    timeout_ms: int = Field(default=3000, ge=1000, le=30000)


def _tx(request: Request, principal: CurrentPrincipal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


@router.get("/webhooks/signing-secret", responses=problem_responses(401))
async def get_signing_secret(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    wrapper = key_wrapper(request.app.state.settings)
    async with _tx(request, principal) as session:
        view = await service.masked_secret(session, wrapper, principal.workspace_id)
    return view.masked()


@router.post("/webhooks/signing-secret/rotate", responses=problem_responses(401))
async def rotate_signing_secret(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    wrapper = key_wrapper(request.app.state.settings)
    async with _tx(request, principal) as session:
        view = await service.rotate_secret(session, wrapper, principal.workspace_id)
    return {**view.masked(), "secret": view.secret}


@router.get("/webhooks/deliveries", responses=problem_responses(401))
async def list_deliveries(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    call_id: str | None = None,
    event: Annotated[str | None, Query(pattern="^(" + "|".join(WEBHOOK_EVENTS) + ")$")] = None,
    status: Annotated[str | None, Query(pattern="^(" + "|".join(DELIVERY_STATUSES) + ")$")] = None,
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=LOG_DAYS)
    where = [WebhookDelivery.workspace_id == principal.workspace_id, WebhookDelivery.created_at >= since]
    if call_id:
        where.append(WebhookDelivery.call_id == call_id)
    if event:
        where.append(WebhookDelivery.event == event)
    if status:
        where.append(WebhookDelivery.status == status)
    async with _tx(request, principal) as session:
        total = int(
            (
                await session.execute(select(func.count()).select_from(WebhookDelivery).where(*where))
            ).scalar_one()
        )
        rows = (
            await session.execute(
                select(WebhookDelivery)
                .where(*where)
                .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
        items = [service.delivery_json(r) for r in rows]
    return {"items": items, **page_meta(total, page, page_size)}


async def _get(request: Request, principal: CurrentPrincipal, delivery_id: str) -> WebhookDelivery:
    async with _tx(request, principal) as session:
        row: WebhookDelivery | None = (
            await session.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.id == delivery_id, WebhookDelivery.workspace_id == principal.workspace_id
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise not_found("webhook delivery")
    return row


@router.get("/webhooks/deliveries/{delivery_id}", responses=problem_responses(401, 404))
async def get_delivery(
    request: Request, principal: CurrentPrincipal, delivery_id: DeliveryId
) -> dict[str, Any]:
    return service.delivery_json(await _get(request, principal, delivery_id), with_body=True)


@router.post(
    "/webhooks/deliveries/{delivery_id}/redeliver", status_code=202, responses=problem_responses(401, 404)
)
async def redeliver(request: Request, principal: CurrentPrincipal, delivery_id: DeliveryId) -> JSONResponse:
    deferred = Deferred()
    async with _tx(request, principal) as session:
        copy = await service.redeliver(session, principal.workspace_id, delivery_id, deferred)
        if copy is None:
            raise not_found("webhook delivery")
        body = service.delivery_json(copy)
    await dispatch(getattr(request.app.state, "jobs", None), deferred)
    return JSONResponse(body, status_code=202)


@router.post("/webhooks/test", responses=problem_responses(401, 422))
async def send_test(body: TestRequest, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    """One signed ``ping`` attempt, no retries; the attempt is also kept in the delivery log."""
    state = request.app.state
    settings = state.settings
    now = datetime.now(UTC)
    delivery_id = new_id("whd")
    payload = service.ping_body(delivery_id, now)
    wrapper = key_wrapper(settings)
    async with _tx(request, principal) as session:
        secrets = await service.signing_secrets(session, wrapper, principal.workspace_id, now)
    raw = payload.encode()
    headers = jobs.headers_for(delivery_id, "ping", raw, secrets, int(now.timestamp()))
    result = await jobs.send_once(
        state.webhook_http,
        body.url,
        raw,
        headers,
        body.timeout_ms,
        allow_http=settings.webhooks_allow_http,
        allow_private=settings.webhooks_allow_private,
        resolver=getattr(state, "webhook_resolver", None),
    )
    if result.error == "url_not_allowed":
        raise ProblemError(422, "url_not_allowed", "URL not allowed", result.response_excerpt)
    attempt = jobs.attempt_json(1, now, result)
    async with _tx(request, principal) as session:
        session.add(
            WebhookDelivery(
                id=delivery_id,
                workspace_id=principal.workspace_id,
                call_id=None,
                event="ping",
                url=body.url,
                timeout_ms=body.timeout_ms,
                body=payload,
                status="succeeded" if result.succeeded else "failed",
                attempts=[attempt],
                next_attempt_at=None,
                completed_at=now,
            )
        )
    return attempt
