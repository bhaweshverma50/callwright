"""Development-only routes, mounted when ENV is not prod and never part of the contract.

* ``GET /v1/dev/mail``: the local IdP's outbox (verification and reset links), newest first.
* ``GET /v1/dev/fake-checkout/{id}``: a stand-in for the hosted checkout page in
  ``STRIPE_MODE=fake``. "Pay" signs a ``checkout.session.completed`` event with the webhook
  secret and runs it through the same verification and handler as real webhooks; "Cancel"
  returns to the cancel URL without writing anything.
"""

from __future__ import annotations

import html
import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text

from app.billing import service as billing
from app.billing.models import CheckoutSession
from app.core.errors import not_found

router = APIRouter(prefix="/dev", tags=["dev"], include_in_schema=False)


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


@router.get("/fake-checkout/{session_id}", response_class=HTMLResponse)
async def fake_checkout_page(session_id: str, request: Request) -> HTMLResponse:
    row = await _checkout(request, session_id)
    sid = html.escape(session_id)
    amount = f"${row.amount_usd:,.2f}"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<title>Fake checkout</title></head><body style="font-family:system-ui;max-width:28rem;margin:4rem auto">
<h1>Fake checkout</h1><p>Development payment page (STRIPE_MODE=fake). No card is charged.</p>
<p>Top-up amount: <strong>{amount}</strong> (status {html.escape(row.status)})</p>
<form method="post" action="{sid}/pay"><button type="submit">Pay {amount}</button></form>
<form method="post" action="{sid}/cancel"><button type="submit">Cancel</button></form>
</body></html>""")


@router.post("/fake-checkout/{session_id}/pay")
async def fake_checkout_pay(session_id: str, request: Request) -> RedirectResponse:
    row = await _checkout(request, session_id)
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
    base = request.app.state.settings.web_base_url.rstrip("/")
    return RedirectResponse(f"{base}/billing?checkout=success", status_code=303)


@router.post("/fake-checkout/{session_id}/cancel")
async def fake_checkout_cancel(session_id: str, request: Request) -> RedirectResponse:
    await _checkout(request, session_id)
    base = request.app.state.settings.web_base_url.rstrip("/")
    return RedirectResponse(f"{base}/billing?checkout=canceled", status_code=303)
