"""Abandoned and expired checkouts, refunds and disputes (T049, US2.2, edge cases)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.billing.models import CheckoutSession
from tests.conftest import Account
from tests.integration.billing.stripe_fixtures import (
    balance,
    completed,
    event,
    post_event,
    start_checkout,
    transaction_types,
)


async def _status(app: FastAPI, account: Account, session_id: str) -> str:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        row = (
            await session.execute(
                select(CheckoutSession).where(CheckoutSession.stripe_session_id == session_id)
            )
        ).scalar_one()
        return row.status


async def test_abandoned_checkout_writes_nothing(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "100.00")
    canceled = await client.post(f"/v1/dev/fake-checkout/{session_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["redirect_url"].endswith("/billing?checkout=canceled")
    assert await transaction_types(client, account) == ["trial_grant"]
    assert await _status(app, account, session_id) == "pending"


async def test_expired_session_writes_no_transaction(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "100.00")
    response = await post_event(client, app, event("checkout.session.expired", {"id": session_id}))
    assert response.json()["outcome"] == "expired"
    assert await _status(app, account, session_id) == "expired"
    assert await transaction_types(client, account) == ["trial_grant"]
    assert await balance(client, account) == "5.000000"


async def test_completed_session_is_marked(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    session_id = await start_checkout(client, account)
    await post_event(client, app, completed(session_id, 2500, f"pi_{session_id}"))
    assert await _status(app, account, session_id) == "completed"
    late_expiry = await post_event(client, app, event("checkout.session.expired", {"id": session_id}))
    assert late_expiry.json()["outcome"] == "unchanged"


async def test_refund_posts_negative_adjustment_once(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "25.00")
    pi = f"pi_{session_id}"
    await post_event(client, app, completed(session_id, 2500, pi))
    charge = {
        "id": f"ch_{session_id}",
        "object": "charge",
        "payment_intent": pi,
        "amount_refunded": 1000,
        "refunds": {"data": [{"id": f"re_{session_id}", "amount": 1000, "status": "succeeded"}]},
    }
    first = await post_event(client, app, event("charge.refunded", charge))
    replay = await post_event(client, app, event("charge.refunded", charge))
    assert first.json()["outcome"] == "adjusted"
    assert replay.json()["outcome"] == "duplicate"
    body = (await client.get("/v1/billing/transactions", headers=account.headers)).json()
    adjustment = body["items"][0]
    assert adjustment["type"] == "adjustment"
    assert adjustment["amount_usd"] == "-10.000000"
    assert adjustment["balance_after_usd"] == "20.000000"
    assert await transaction_types(client, account) == ["adjustment", "top_up", "trial_grant"]


async def test_dispute_posts_negative_adjustment(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "25.00")
    pi = f"pi_{session_id}"
    await post_event(client, app, completed(session_id, 2500, pi))
    dispute = {"id": f"dp_{session_id}", "object": "dispute", "payment_intent": pi, "amount": 2500}
    assert (await post_event(client, app, event("charge.dispute.created", dispute))).json()[
        "outcome"
    ] == "adjusted"
    assert await balance(client, account) == "5.000000"


async def test_refund_for_unknown_payment_is_ignored(client: httpx.AsyncClient, app: FastAPI) -> None:
    charge = {
        "id": "ch_x",
        "payment_intent": "pi_never_seen",
        "amount_refunded": 500,
        "refunds": {"data": []},
    }
    response = await post_event(client, app, event("charge.refunded", charge))
    assert response.status_code == 200
    assert response.json()["outcome"] == "unknown_payment"


async def test_idempotency_key_reuses_the_checkout(client: httpx.AsyncClient, account: Account) -> None:
    headers = account.headers | {"Idempotency-Key": "topup-1"}
    first = await client.post("/v1/billing/checkout-sessions", json={"amount_usd": "25.00"}, headers=headers)
    second = await client.post("/v1/billing/checkout-sessions", json={"amount_usd": "25.00"}, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["checkout_url"] == second.json()["checkout_url"]


async def test_invalid_amounts_rejected_by_the_api(client: httpx.AsyncClient, account: Account) -> None:
    for amount in ("4.00", "10000.01", "5.555", "4"):
        response = await client.post(
            "/v1/billing/checkout-sessions", json={"amount_usd": amount}, headers=account.headers
        )
        assert response.status_code == 422, amount
        assert response.json()["errors"][0]["pointer"] == "/amount_usd"
