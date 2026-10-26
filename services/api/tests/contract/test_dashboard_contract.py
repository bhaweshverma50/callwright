"""Contract tests for the dashboard (006 T039)."""

from __future__ import annotations

import httpx

from tests.calls_support import SeededCalls
from tests.contract.conftest import check


async def test_stats(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    for params in (
        {},
        {"period": "last_7_days", "tz": "Asia/Kolkata"},
        {"period": "all_time"},
        {"period": "custom", "start_date": "2025-01-01", "end_date": "2026-10-30"},
        {"agent_ids": seeded_calls.data.agent_ids[1]},
    ):
        assert check(await client.get("/v1/dashboard/stats", params=params, headers=h)).status_code == 200
    bad = check(
        await client.get(
            "/v1/dashboard/stats",
            params={"period": "custom", "start_date": "2026-10-10", "end_date": "2026-10-01"},
            headers=h,
        )
    )
    assert bad.status_code == 422 and bad.json()["detail"] == "End date must be on or after start date."
    assert check(await client.get("/v1/dashboard/stats")).status_code == 401


async def test_quality_and_health(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    assert check(await client.get("/v1/dashboard/quality", headers=h)).status_code == 200
    assert (
        check(await client.get("/v1/dashboard/quality", params={"compare": "false"}, headers=h)).status_code
        == 200
    )
    assert check(await client.get("/v1/dashboard/agent-health", headers=h)).status_code == 200
