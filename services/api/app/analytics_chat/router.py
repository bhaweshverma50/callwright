"""``POST /v1/analytics/chat`` and ``GET /v1/analytics/catalog`` (006 T068, FR-023 to FR-027, FR-041).

Order of checks: replay of the Idempotency-Key (stored answer, no new charge), 20 questions per
minute per user (429), balance at or below zero (402), the assistant (a provider failure is 503,
never charged), then one ``analytics_chat`` feature charge per answered question. Declined
questions are not charged. Every request is logged in ``analytics_chat_requests`` for 30 days.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, Request
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.agents.models import Agent
from app.analytics_chat import assistant
from app.analytics_chat.catalog import catalog_json
from app.analytics_chat.models import AnalyticsChatRequest
from app.analytics_chat.schemas import ChatRequest
from app.billing import service as billing
from app.core.auth import CurrentPrincipal
from app.core.errors import ProblemError, field_error, problem_responses, too_many_requests, validation_failed
from app.core.money import SIX
from app.core.rate_limit import RateLimiter
from app.llms.charges import charge_tokens
from app.llms.client import ModelError, ModelTimeout, token_cost
from app.llms.runtime import runtime

router = APIRouter(tags=["analytics"])
tracer = trace.get_tracer("app.analytics_chat")


def unavailable() -> ProblemError:
    return ProblemError(
        503,
        "assistant_unavailable",
        "Assistant unavailable",
        "The assistant could not answer right now. Nothing was charged; try again in a moment.",
    )


@router.get("/analytics/catalog", responses=problem_responses(401))
async def get_catalog(principal: CurrentPrincipal) -> dict[str, Any]:
    return catalog_json()


async def _log(
    request: Request, principal: Any, key: str, question: str, outcome: str, **fields: Any
) -> None:
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        session.add(
            AnalyticsChatRequest(
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                idempotency_key=key,
                question=question[:2000],
                outcome=outcome,
                **fields,
            )
        )


@router.post("/analytics/chat", responses=problem_responses(401, 402, 422, 429, 503))
async def ask(
    body: ChatRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> dict[str, Any]:
    state = request.app.state
    settings = state.settings
    started = time.monotonic()
    question = body.messages[-1].content
    try:
        zone = ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise validation_failed(
            [field_error("/timezone", "invalid_format", "Use an IANA timezone.")]
        ) from exc
    tx = state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)
    async with tx as session:
        stored = (
            await session.execute(
                select(AnalyticsChatRequest.response).where(
                    AnalyticsChatRequest.workspace_id == principal.workspace_id,
                    AnalyticsChatRequest.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if stored is not None:
            replay: dict[str, Any] = stored
            return replay
        balance = await billing.get_balance(session, principal.workspace_id)
        agents = {
            a.id: a.name
            for a in (
                await session.execute(select(Agent.id, Agent.name).where(Agent.deleted_at.is_(None)))
            ).all()
        }
    limit = await RateLimiter(state.redis).hit(
        "analytics_chat", principal.user_id, limit=settings.analytics_chat_rate_limit_per_min, window_s=60
    )
    if not limit.allowed:
        raise too_many_requests(limit.retry_after_s, "Too many questions. Try again in a minute.")
    if balance <= 0:
        await _log(
            request,
            principal,
            f"{idempotency_key}#refused-{uuid.uuid4().hex[:8]}",
            question,
            "refused_balance",
        )
        raise billing.insufficient_credit("Add funds to ask about your data.")
    with tracer.start_as_current_span("analytics_chat.answer"):
        try:
            result = await assistant.answer(
                state.db,
                runtime().llm,
                settings.analytics_chat_model,
                workspace_id=principal.workspace_id,
                messages=body.messages,
                tz=zone.key,
                today=datetime.now(zone).date(),
                agents=agents,
                planner=getattr(state, "analytics_planner", None),
            )
        except (ModelError, ModelTimeout, DBAPIError) as exc:
            await _log(
                request, principal, f"{idempotency_key}#failed-{uuid.uuid4().hex[:8]}", question, "failed"
            )
            raise unavailable() from exc
    raw = token_cost(result.model, result.input_tokens, result.output_tokens).quantize(SIX)
    charged: Decimal | None = None
    txn_id: str | None = None
    response = dict(result.body)
    latency_ms = int((time.monotonic() - started) * 1000)
    async with state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        if result.body["outcome"] == "answered":
            charge = await charge_tokens(
                session,
                workspace_id=principal.workspace_id,
                feature_key="analytics_chat",
                tokens=result.input_tokens + result.output_tokens,
                raw_cost_usd=raw,
                idempotency_key=f"analytics_chat:{idempotency_key}",
            )
            charged = charge.usage_event.billable_cost_usd
            txn_id = charge.txn.id if charge.txn is not None else None
        response["charged_usd"] = float(charged) if charged is not None else None
        session.add(
            AnalyticsChatRequest(
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                idempotency_key=idempotency_key,
                question=question[:2000],
                metric_queries=result.queries,
                outcome=result.body["outcome"],
                response=response,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                raw_cost_usd=raw,
                charge_txn_id=txn_id,
                latency_ms=latency_ms,
            )
        )
    return response
