"""/v1/billing and the Stripe webhook (contracts/billing.yaml)."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from app.billing import service
from app.billing.schemas import BalanceOut, CheckoutOut, CheckoutRequest, transaction_json
from app.billing.stripe_gateway import SignatureError
from app.core.auth import CurrentPrincipal
from app.core.errors import ProblemError, not_found, problem_responses
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])

TransactionId = Annotated[str, Depends(path_id("txn", "transaction", "transaction_id"))]


def _tx(request: Request, principal: CurrentPrincipal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


@router.get("/billing/balance", response_model=BalanceOut, responses=problem_responses(401))
async def get_balance(request: Request, principal: CurrentPrincipal) -> BalanceOut:
    async with _tx(request, principal) as session:
        seq, balance = await service.latest_seq_and_balance(session, principal.workspace_id)
    return BalanceOut(balance_usd=f"{balance:.6f}", as_of_seq=seq)


@router.post(
    "/billing/checkout-sessions",
    status_code=201,
    response_model=CheckoutOut,
    responses=problem_responses(401, 422),
)
async def create_checkout_session(
    body: CheckoutRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> CheckoutOut:
    async with _tx(request, principal) as session:
        row = await service.create_checkout(
            session,
            request.app.state.stripe,
            workspace_id=principal.workspace_id,
            amount_usd=body.amount(),
            web_base_url=request.app.state.settings.web_base_url,
            idempotency_key=idempotency_key,
        )
        return CheckoutOut(checkout_url=row.checkout_url, expires_at=row.expires_at)


@router.get("/billing/transactions", responses=problem_responses(401))
async def list_transactions(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    type: Annotated[str | None, Query(pattern="^(" + "|".join(service.TXN_TYPES) + ")$")] = None,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_transactions(
            session, principal.workspace_id, page=page, page_size=page_size, type=type
        )
        costs = await service.call_costs_for(
            session, [r.call_id for r in rows if r.type == "call_charge" and r.call_id]
        )
    items = [transaction_json(r, costs.get(r.call_id or "")) for r in rows]
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/billing/transactions/{transaction_id}", responses=problem_responses(401, 404))
async def get_transaction(
    transaction_id: TransactionId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        found = await service.get_transaction(session, principal.workspace_id, transaction_id)
    if found is None:
        raise not_found("transaction")
    txn, cost = found
    return transaction_json(txn, cost)


@router.post("/webhooks/stripe", tags=["webhooks"], responses=problem_responses(400))
async def stripe_webhook(request: Request) -> Response:
    payload = await request.body()
    try:
        event = request.app.state.stripe.verify_webhook(payload, request.headers.get("stripe-signature"))
    except SignatureError as exc:
        raise ProblemError(
            400, "invalid_signature", "Signature invalid", "The Stripe-Signature header did not verify."
        ) from exc
    outcome = await service.handle_stripe_event(request.app.state.db, event)
    logger.info("stripe event %s %s: %s", event.get("id"), event.get("type"), outcome)
    return JSONResponse({"received": True, "outcome": outcome}, status_code=200)
