"""Development-only routes, never part of the contract.

* ``GET /v1/dev/mail`` (``router``): the local IdP's outbox (verification and reset links),
  newest first. Mounted when ``Settings.dev_routes_enabled`` (ENV dev/test or
  ``ENABLE_DEV_ROUTES=true``).
* ``/v1/dev/fake-checkout/{id}`` (``checkout_router``): the API behind the web app's test checkout
  page (``/checkout/{id}``) in ``STRIPE_MODE=fake``, mounted when ``Settings.fake_checkout_enabled``
  (follows the dev routes unless ``ENABLE_FAKE_CHECKOUT`` says otherwise), so a hosted demo can
  take fake payments without exposing the mailbox. ``GET`` describes the session and lists the
  test cards. ``POST .../pay`` takes card details and, like Stripe's test cards, decides the
  outcome by card number: a success signs a ``checkout.session.completed`` event with the webhook
  secret and runs it through the same verification and handler as real webhooks; a decline
  answers 402 with Stripe's decline code and writes nothing. ``POST .../cancel`` returns the
  cancel URL without writing anything.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.billing import service as billing
from app.billing.models import CheckoutSession
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.workspaces.models import Workspace

router = APIRouter(prefix="/dev", tags=["dev"], include_in_schema=False)
checkout_router = APIRouter(prefix="/dev", tags=["dev"], include_in_schema=False)


@router.get("/mail")
async def dev_mail(request: Request) -> dict[str, Any]:
    outbox = getattr(request.app.state.idp, "outbox", None)
    if outbox is None:
        raise not_found("mailbox")
    return {
        "items": [
            {
                "to": m.to,
                "kind": m.kind,
                "link": m.link,
                "token_hash": m.token_hash,
                "sent_at": m.sent_at.isoformat(),
            }
            for m in reversed(outbox)
        ]
    }


async def _checkout(request: Request, session_id: str) -> CheckoutSession:
    db = request.app.state.db
    async with db.transaction() as s:
        ws = (await s.execute(text("select billing_checkout_workspace(:id)"), {"id": session_id})).scalar()
    if not ws:
        raise not_found("checkout session")
    async with db.transaction(workspace_id=ws) as s:
        row: CheckoutSession = (
            await s.execute(select(CheckoutSession).where(CheckoutSession.stripe_session_id == session_id))
        ).scalar_one()
    return row


# Stripe's test card numbers and what each one does (https://docs.stripe.com/testing).
TEST_CARDS: tuple[dict[str, str], ...] = (
    {"number": "4242424242424242", "brand": "visa", "label": "Payment succeeds", "outcome": "succeeded"},
    {
        "number": "5555555555554444",
        "brand": "mastercard",
        "label": "Payment succeeds",
        "outcome": "succeeded",
    },
    {"number": "4000000000000002", "brand": "visa", "label": "Card declined", "outcome": "card_declined"},
    {
        "number": "4000000000009995",
        "brand": "visa",
        "label": "Insufficient funds",
        "outcome": "insufficient_funds",
    },
    {"number": "4000000000000069", "brand": "visa", "label": "Expired card", "outcome": "expired_card"},
    {"number": "4000000000000127", "brand": "visa", "label": "Incorrect CVC", "outcome": "incorrect_cvc"},
    {
        "number": "4000000000000119",
        "brand": "visa",
        "label": "Processing error",
        "outcome": "processing_error",
    },
)
DECLINES = {
    "card_declined": "Your card was declined.",
    "insufficient_funds": "Your card has insufficient funds.",
    "expired_card": "Your card has expired.",
    "incorrect_cvc": "Your card's security code is incorrect.",
    "processing_error": "An error occurred while processing your card. Try again in a little bit.",
}
OUTCOMES = {c["number"]: c["outcome"] for c in TEST_CARDS}


class CardDetails(BaseModel):
    card_number: str = Field(max_length=32)
    exp_month: int
    exp_year: int
    cvc: str = Field(max_length=8)
    name: str = Field(max_length=120)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _card_errors(card: CardDetails, now: datetime) -> tuple[str, list[dict[str, str]]]:
    """The card number's digits and every field that would not pass a real card form."""
    digits = card.card_number.replace(" ", "").replace("-", "")
    errors = []
    if not digits.isdigit() or not 13 <= len(digits) <= 19 or not _luhn(digits):
        errors.append(field_error("/card_number", "invalid_number", "Your card number is invalid."))
    year = card.exp_year + 2000 if card.exp_year < 100 else card.exp_year
    if not 1 <= card.exp_month <= 12:
        errors.append(field_error("/exp_month", "invalid_expiry", "Your card's expiration date is invalid."))
    elif (year, card.exp_month) < (now.year, now.month):
        errors.append(
            field_error(
                "/exp_year", "invalid_expiry_year_past", "Your card's expiration year is in the past."
            )
        )
    if not card.cvc.isdigit() or not 3 <= len(card.cvc) <= 4:
        errors.append(field_error("/cvc", "invalid_cvc", "Your card's security code is incomplete."))
    if not card.name.strip():
        errors.append(field_error("/name", "required", "Enter the name on the card."))
    return digits, errors


def _web(request: Request, path: str) -> str:
    base: str = request.app.state.settings.web_base_url
    return base.rstrip("/") + path


@checkout_router.get("/fake-checkout/{session_id}")
async def fake_checkout_session(session_id: str, request: Request) -> dict[str, Any]:
    row = await _checkout(request, session_id)
    async with request.app.state.db.transaction(workspace_id=row.workspace_id) as s:
        workspace = await s.get(Workspace, row.workspace_id)
    expired = row.status == "pending" and row.expires_at <= datetime.now(UTC)
    return {
        "id": session_id,
        "amount_usd": f"{row.amount_usd:.2f}",
        "status": "expired" if expired else row.status,
        "expires_at": row.expires_at.isoformat(),
        "workspace_name": workspace.name if workspace else None,
        "success_url": _web(request, "/billing?checkout=success"),
        "cancel_url": _web(request, "/billing?checkout=canceled"),
        "test_cards": list(TEST_CARDS),
    }


@checkout_router.post("/fake-checkout/{session_id}/pay")
async def fake_checkout_pay(session_id: str, card: CardDetails, request: Request) -> dict[str, Any]:
    row = await _checkout(request, session_id)
    now = datetime.now(UTC)
    if row.status == "expired" or (row.status == "pending" and row.expires_at <= now):
        raise ProblemError(
            410,
            "checkout_expired",
            "Checkout expired",
            "This checkout has expired. Start a new top-up from Billing.",
        )
    digits, errors = _card_errors(card, now)
    if errors:
        raise validation_failed(errors)
    outcome = OUTCOMES.get(digits, "card_declined")
    if outcome != "succeeded":
        detail = DECLINES[outcome]
        if digits not in OUTCOMES:
            detail += " This is a test checkout: use one of the test cards."
        raise ProblemError(402, outcome, "Payment declined", detail, extra={"decline_code": outcome})
    cents = int(row.amount_usd * 100)
    event = {
        "id": f"evt_fake_{session_id}",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "payment_status": "paid",
                "amount_total": cents,
                "currency": "usd",
                "payment_intent": f"pi_fake_{session_id}",
                "client_reference_id": row.workspace_id,
                "metadata": {"workspace_id": row.workspace_id},
            }
        },
    }
    payload = json.dumps(event).encode()
    gateway = request.app.state.stripe
    verified = gateway.verify_webhook(payload, gateway.sign(payload))
    await billing.handle_stripe_event(request.app.state.db, verified)
    return {"status": "paid", "redirect_url": _web(request, "/billing?checkout=success")}


@checkout_router.post("/fake-checkout/{session_id}/cancel")
async def fake_checkout_cancel(session_id: str, request: Request) -> dict[str, Any]:
    await _checkout(request, session_id)
    return {"status": "canceled", "redirect_url": _web(request, "/billing?checkout=canceled")}
