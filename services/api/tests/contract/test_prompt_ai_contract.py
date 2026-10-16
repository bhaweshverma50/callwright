"""contracts/prompt_ai.yaml: 200, 401, 402, 422, 429, 504 (T076)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from app.billing import service as billing
from tests.conftest import Account, signup
from tests.contract.conftest import check

URL = "/v1/prompt-ai/generate"
ASK = {
    "messages": [{"role": "user", "content": "A receptionist for a dental clinic that books appointments"}]
}


async def drain(app: FastAPI, account: Account) -> None:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        balance = await billing.get_balance(session, account.workspace_id)
        await billing.post_transaction(
            session,
            workspace_id=account.workspace_id,
            type="adjustment",
            amount_usd=-balance,
            description="test: drain",
            external_ref=f"drain:{account.workspace_id}",
        )


async def test_200_with_proposal(client: httpx.AsyncClient, account: Account) -> None:
    response = check(await client.post(URL, json={**ASK, "current": None}, headers=account.headers))
    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["prompt"] and Decimal(body["billed_usd"]) > 0


async def test_401_422(client: httpx.AsyncClient, account: Account) -> None:
    assert check(await client.post(URL, json=ASK)).status_code == 401
    bad = check(await client.post(URL, json={"messages": []}, headers=account.headers))
    assert bad.status_code == 422


async def test_402_when_balance_is_zero(client: httpx.AsyncClient, app: FastAPI) -> None:
    broke = await signup(client, app)
    await drain(app, broke)
    response = check(await client.post(URL, json=ASK, headers=broke.headers))
    assert response.status_code == 402 and response.json()["code"] == "insufficient_credit"


async def test_429_over_the_limit(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy = await signup(client, app)
    monkeypatch.setattr(
        app.state, "settings", app.state.settings.model_copy(update={"prompt_ai_rate_limit_per_min": 1})
    )
    assert (await client.post(URL, json=ASK, headers=busy.headers)).status_code == 200
    limited = check(await client.post(URL, json=ASK, headers=busy.headers))
    assert limited.status_code == 429 and limited.headers["retry-after"]


async def test_504_on_timeout(client: httpx.AsyncClient, account: Account) -> None:
    response = check(
        await client.post(
            URL,
            json={"messages": [{"role": "user", "content": "draft one [timeout]"}]},
            headers=account.headers,
        )
    )
    assert response.status_code == 504 and response.json()["code"] == "assistant_timeout"
