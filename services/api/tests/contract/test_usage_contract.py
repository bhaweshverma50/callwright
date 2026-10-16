"""contracts/usage.yaml (T075)."""

from __future__ import annotations

from decimal import Decimal

import httpx
from fastapi import FastAPI

from app.billing import service
from tests.conftest import Account
from tests.contract.conftest import check


async def test_usage_200_401_422(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await service.charge_feature(
            session,
            workspace_id=account.workspace_id,
            feature_key="eval.tone",
            quantity=Decimal(1),
            unit="runs",
            raw_cost_usd=Decimal("0.0002"),
            billable_cost_usd=Decimal("0.0004"),
            idempotency_key="u1",
        )
    body = check(await client.get("/v1/usage", headers=account.headers)).json()
    assert body["rows"][0]["feature"] == "evaluations"
    assert check(await client.get("/v1/usage")).status_code == 401
    bad = check(await client.get("/v1/usage?from=2026-10-10&to=2026-10-01", headers=account.headers))
    assert bad.status_code == 422
