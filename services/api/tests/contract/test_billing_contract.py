"""contracts/billing.yaml (T046)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account
from tests.contract.conftest import check
from tests.integration.billing.stripe_fixtures import completed, post_event, start_checkout


async def test_balance_200_401(client: httpx.AsyncClient, account: Account) -> None:
    body = check(await client.get("/v1/billing/balance", headers=account.headers)).json()
    assert body == {"balance_usd": "5.000000", "as_of_seq": 1}
    assert check(await client.get("/v1/billing/balance")).status_code == 401


async def test_checkout_201_401_422(client: httpx.AsyncClient, account: Account) -> None:
    created = check(
        await client.post(
            "/v1/billing/checkout-sessions", json={"amount_usd": "25.00"}, headers=account.headers
        )
    )
    assert created.status_code == 201
    unauth = check(await client.post("/v1/billing/checkout-sessions", json={"amount_usd": "25.00"}))
    assert unauth.status_code == 401
    bad = check(
        await client.post(
            "/v1/billing/checkout-sessions", json={"amount_usd": "4.00"}, headers=account.headers
        )
    )
    assert bad.status_code == 422


async def test_transactions_list_and_detail(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    session_id = await start_checkout(client, account)
    check(await post_event(client, app, completed(session_id, 2500, f"pi_{session_id}")))
    listed = check(await client.get("/v1/billing/transactions?page=1&page_size=1", headers=account.headers))
    body = listed.json()
    assert body["total"] == 2 and body["total_pages"] == 2 and len(body["items"]) == 1
    filtered = check(await client.get("/v1/billing/transactions?type=trial_grant", headers=account.headers))
    assert [i["type"] for i in filtered.json()["items"]] == ["trial_grant"]
    txn_id = body["items"][0]["id"]
    assert (
        check(await client.get(f"/v1/billing/transactions/{txn_id}", headers=account.headers)).status_code
        == 200
    )
    missing = check(
        await client.get("/v1/billing/transactions/txn_01ARZ3NDEKTSV4RRFFQ69G5FAV", headers=account.headers)
    )
    assert missing.status_code == 404
    assert check(await client.get("/v1/billing/transactions")).status_code == 401
    assert check(await client.get(f"/v1/billing/transactions/{txn_id}")).status_code == 401


async def test_webhook_200_400(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    session_id = await start_checkout(client, account)
    assert check(await post_event(client, app, completed(session_id, 2500, "pi_c"))).status_code == 200
    bad = check(await post_event(client, app, completed(session_id, 2500, "pi_c"), secret="whsec_bad"))
    assert bad.status_code == 400
