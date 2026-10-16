"""Exactly-once crediting from signed Stripe webhooks (T048, US2.1, US2.3, SC-005)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account
from tests.integration.billing.stripe_fixtures import (
    balance,
    completed,
    event,
    post_event,
    start_checkout,
    transaction_types,
)


async def test_completed_checkout_posts_one_top_up(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "25.00")
    response = await post_event(client, app, completed(session_id, 2500, f"pi_{session_id}"))
    assert response.status_code == 200
    assert response.json()["outcome"] == "credited"
    assert await balance(client, account) == "30.000000"
    body = (await client.get("/v1/billing/transactions", headers=account.headers)).json()
    top_up = body["items"][0]
    assert top_up["type"] == "top_up"
    assert top_up["amount_usd"] == "25.000000"
    assert top_up["balance_after_usd"] == "30.000000"


async def test_replayed_event_credits_once(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    session_id = await start_checkout(client, account, "25.00")
    body = completed(session_id, 2500, f"pi_{session_id}")
    first = await post_event(client, app, body)
    replay = await post_event(client, app, body)
    async_paid = await post_event(
        client,
        app,
        completed(session_id, 2500, f"pi_{session_id}", type="checkout.session.async_payment_succeeded"),
    )
    assert [r.status_code for r in (first, replay, async_paid)] == [200, 200, 200]
    assert replay.json()["outcome"] == "duplicate"
    assert async_paid.json()["outcome"] == "duplicate"
    assert await transaction_types(client, account) == ["top_up", "trial_grant"]
    assert await balance(client, account) == "30.000000"


async def test_unpaid_completion_waits_for_async_payment(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "100.00")
    waiting = await post_event(client, app, completed(session_id, 10000, f"pi_{session_id}", paid=False))
    assert waiting.json()["outcome"] == "awaiting_payment"
    assert await balance(client, account) == "5.000000"
    paid = await post_event(
        client,
        app,
        completed(session_id, 10000, f"pi_{session_id}", type="checkout.session.async_payment_succeeded"),
    )
    assert paid.json()["outcome"] == "credited"
    assert await balance(client, account) == "105.000000"


async def test_invalid_signature_is_400(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    session_id = await start_checkout(client, account)
    response = await post_event(client, app, completed(session_id, 2500, "pi_x"), secret="whsec_wrong")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_signature"
    missing = await client.post("/v1/webhooks/stripe", json=completed(session_id, 2500, "pi_x"))
    assert missing.status_code == 400
    assert await balance(client, account) == "5.000000"


async def test_unknown_event_is_200(client: httpx.AsyncClient, app: FastAPI) -> None:
    response = await post_event(client, app, event("customer.created", {"id": "cus_1"}))
    assert response.status_code == 200
    assert response.json()["outcome"] == "ignored"


async def test_completion_for_unknown_session_is_ignored(client: httpx.AsyncClient, app: FastAPI) -> None:
    response = await post_event(client, app, completed("cs_unknown_123", 2500, "pi_unknown"))
    assert response.status_code == 200
    assert response.json()["outcome"] == "unknown_session"


async def test_fake_checkout_pay_page_credits(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account, "25.00")
    page = await client.get(f"/v1/dev/fake-checkout/{session_id}")
    assert page.status_code == 200 and "$25.00" in page.text
    paid = await client.post(f"/v1/dev/fake-checkout/{session_id}/pay")
    assert paid.status_code == 303
    assert paid.headers["location"].endswith("/billing?checkout=success")
    again = await client.post(f"/v1/dev/fake-checkout/{session_id}/pay")
    assert again.status_code == 303
    assert await balance(client, account) == "30.000000"
