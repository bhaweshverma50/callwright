"""Usage report window and grouping (T076, FR-014, US4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi import FastAPI

from app.billing import service
from tests.conftest import Account


async def _feature(app: FastAPI, ws: str, key: str, billable: str, raw: str, when: datetime) -> None:
    async with app.state.db.transaction(workspace_id=ws) as session:
        await service.charge_feature(
            session,
            workspace_id=ws,
            feature_key=key,
            quantity=Decimal(1),
            unit="runs",
            raw_cost_usd=Decimal(raw),
            billable_cost_usd=Decimal(billable),
            idempotency_key=f"{key}-{when.isoformat()}",
            occurred_at=when,
        )


async def test_empty_window(client: httpx.AsyncClient, account: Account) -> None:
    response = await client.get("/v1/usage", headers=account.headers)
    assert response.status_code == 200
    body = response.json()
    today = datetime.now(UTC).date()
    assert body["window"] == {"from": (today - timedelta(days=30)).isoformat(), "to": today.isoformat()}
    assert body["rows"] == []
    assert body["total_raw_cost_usd"] == body["total_billable_cost_usd"] == "0.000000"


async def test_in_range_rows_grouped_by_family(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    ws = account.workspace_id
    await _feature(
        app, ws, "eval.intent_fulfillment", "0.0004", "0.0002", datetime(2026, 9, 20, 12, tzinfo=UTC)
    )
    await _feature(app, ws, "eval.tone", "0.0006", "0.0003", datetime(2026, 9, 30, 23, 59, tzinfo=UTC))
    await _feature(app, ws, "prompt_generation", "0.01", "0.005", datetime(2026, 9, 10, tzinfo=UTC))
    await _feature(
        app, ws, "simulator.persona_turn", "0.02", "0.01", datetime(2026, 8, 1, tzinfo=UTC)
    )  # outside
    await _feature(
        app, ws, "analytics_chat", "0.03", "0.01", datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    )  # after `to`
    response = await client.get("/v1/usage?from=2026-09-10&to=2026-09-30", headers=account.headers)
    body = response.json()
    assert body["window"] == {"from": "2026-09-10", "to": "2026-09-30"}
    rows = {r["feature"]: r for r in body["rows"]}
    assert set(rows) == {"evaluations", "prompt_generation"}
    evaluations = rows["evaluations"]
    assert evaluations["event_count"] == 2
    assert evaluations["billable_cost_usd"] == "0.001000"
    assert evaluations["raw_cost_usd"] == "0.000500"
    assert {d["feature_key"] for d in evaluations["details"]} == {"eval.intent_fulfillment", "eval.tone"}
    assert body["total_billable_cost_usd"] == "0.011000"
    assert body["total_raw_cost_usd"] == "0.005500"
    total = sum(Decimal(r["billable_cost_usd"]) for r in body["rows"])
    assert Decimal(body["total_billable_cost_usd"]) == total


async def test_window_limits(client: httpx.AsyncClient, account: Account) -> None:
    too_long = await client.get("/v1/usage?from=2025-01-01&to=2026-01-02", headers=account.headers)
    assert too_long.status_code == 422
    assert too_long.json()["errors"][0]["pointer"] == "/from"
    reversed_ = await client.get("/v1/usage?from=2026-09-30&to=2026-09-01", headers=account.headers)
    assert reversed_.status_code == 422
    assert reversed_.json()["errors"][0]["pointer"] == "/to"
    max_window = date(2026, 1, 1)
    ok = await client.get(
        f"/v1/usage?from={max_window.isoformat()}&to={(max_window + timedelta(days=365)).isoformat()}",
        headers=account.headers,
    )
    assert ok.status_code == 200
