"""Signed Stripe event fixtures for webhook tests."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import FastAPI
from ulid import ULID

from app.billing.stripe_gateway import sign_payload
from tests.conftest import Account


def event(type: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"evt_{ULID()}", "object": "event", "type": type, "data": {"object": obj}}


def completed(
    session_id: str,
    cents: int,
    payment_intent: str,
    *,
    paid: bool = True,
    type: str = "checkout.session.completed",
) -> dict[str, Any]:
    return event(
        type,
        {
            "id": session_id,
            "object": "checkout.session",
            "payment_status": "paid" if paid else "unpaid",
            "amount_total": cents,
            "payment_intent": payment_intent,
        },
    )


async def post_event(
    client: httpx.AsyncClient, app: FastAPI, body: dict[str, Any], *, secret: str | None = None
) -> httpx.Response:
    payload = json.dumps(body).encode()
    key = secret or app.state.settings.stripe_webhook_secret.get_secret_value()
    return await client.post(
        "/v1/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": sign_payload(payload, key), "content-type": "application/json"},
    )


async def start_checkout(client: httpx.AsyncClient, account: Account, amount: str = "25.00") -> str:
    response = await client.post(
        "/v1/billing/checkout-sessions", json={"amount_usd": amount}, headers=account.headers
    )
    assert response.status_code == 201, response.text
    url: str = response.json()["checkout_url"]
    return url.rsplit("/", 1)[1]


async def transaction_types(client: httpx.AsyncClient, account: Account) -> list[str]:
    body = (await client.get("/v1/billing/transactions", headers=account.headers)).json()
    return [item["type"] for item in body["items"]]


async def balance(client: httpx.AsyncClient, account: Account) -> str:
    value: str = (await client.get("/v1/billing/balance", headers=account.headers)).json()["balance_usd"]
    return value
