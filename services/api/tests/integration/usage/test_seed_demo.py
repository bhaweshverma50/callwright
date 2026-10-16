"""The quickstart seeder (T081) produces in-window and out-of-window rows."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.usage.seed_demo import seed
from tests.conftest import Account


async def test_seed_demo(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    await seed(app.state.db, account.workspace_id)
    body = (await client.get("/v1/usage", headers=account.headers)).json()
    rows = {r["feature"]: r for r in body["rows"]}
    assert rows["calls"]["billable_cost_usd"] == "0.477000"
    assert rows["evaluations"]["event_count"] == 1
    assert body["total_billable_cost_usd"] == "0.477400"
