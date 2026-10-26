"""Dashboard totals equal an independent recount of the seeded calls (006 T042, SC-004, FR-022)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from tests.calls_support import SeededCalls
from tests.runtime_support import owner_sql

FINISHED = ("ended", "processing", "completed")


def _rows(workspace_id: str, start: datetime, end: datetime) -> list[tuple]:
    return owner_sql(
        """select id, agent_id, status, channel, disconnect_reason, sentiment, billable_seconds,
                  cost_total_usd, created_at, origin
             from calls where workspace_id = %s and created_at >= %s and created_at < %s""",
        (workspace_id, start, end),
    )


async def test_last_30_days_recount(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    tz = "Asia/Kolkata"
    body = (
        await client.get(
            "/v1/dashboard/stats", params={"period": "last_30_days", "tz": tz}, headers=seeded_calls.a.headers
        )
    ).json()
    start = datetime.fromisoformat(body["window"]["from"])
    end = datetime.fromisoformat(body["window"]["to"])
    assert end - start == timedelta(days=30)
    rows = [
        r for r in _rows(seeded_calls.a.workspace_id, start, end) if r[9] == "live" and r[2] != "in_progress"
    ]
    assert rows, "seed should have calls in the window"
    kpis = body["kpis"]
    assert kpis["total_calls"] == len(rows)
    finished = [r for r in rows if r[2] in FINISHED]
    assert kpis["total_duration_s"] == sum(r[6] or 0 for r in finished)
    cost = sum((r[7] or Decimal(0)) for r in finished)
    assert Decimal(str(kpis["total_cost_usd"])) == cost
    assert kpis["daily_avg_calls"] == round(len(rows) / 30, 2)
    assert body["bucket"] == "day" and len(body["series"]) == 30
    assert sum(s["total_calls"] for s in body["series"]) == len(rows)
    assert body["channels"] == {
        c: sum(1 for r in rows if r[3] == c) for c in ("web", "sip_inbound", "sip_outbound", "whatsapp")
    }
    assert body["disconnect_reasons"] == dict(Counter(r[4] for r in rows if r[4]))
    assert sum(body["sentiment"].values()) == len(rows)
    assert sum(d["total_calls"] for d in body["distribution"]) == len(rows)
    zone = ZoneInfo(tz)
    days = Counter(r[8].astimezone(zone).date() for r in rows)
    top = max(days.values())
    assert kpis["peak_day"]["total_calls"] == top
    assert (
        kpis["median_turn_latency_ms"] is not None
        and kpis["p95_turn_latency_ms"] >= kpis["median_turn_latency_ms"]
    )


async def test_test_and_simulation_calls_excluded(
    client: httpx.AsyncClient, seeded_calls: SeededCalls
) -> None:
    body = (
        await client.get("/v1/dashboard/stats", params={"period": "all_time"}, headers=seeded_calls.a.headers)
    ).json()
    live = owner_sql(
        "select count(*) from calls where workspace_id = %s and origin = 'live' and status <> 'in_progress'",
        (seeded_calls.a.workspace_id,),
    )[0][0]
    assert body["kpis"]["total_calls"] == live


async def test_agent_filter_and_other_workspace(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    agent = seeded_calls.data.agent_ids[0]
    body = (
        await client.get(
            "/v1/dashboard/stats",
            params={"period": "last_90_days", "agent_ids": agent},
            headers=seeded_calls.a.headers,
        )
    ).json()
    assert [d["agent_id"] for d in body["distribution"]] == [agent]
    empty = (
        await client.get("/v1/dashboard/stats", params={"period": "all_time"}, headers=seeded_calls.b.headers)
    ).json()
    assert (
        empty["kpis"]["total_calls"] == 0
        and empty["distribution"] == []
        and empty["kpis"]["peak_day"] is None
    )


async def test_kolkata_counts_late_utc_call_next_day(
    client: httpx.AsyncClient, seeded_calls: SeededCalls
) -> None:
    yesterday = datetime.now(UTC).date() - timedelta(days=3)
    late = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 30, tzinfo=UTC)
    ref = seeded_calls.data.reference_call_id
    original = owner_sql("select created_at from calls where id = %s", (ref,))[0][0]
    owner_sql("update calls set created_at = %s where id = %s", (late, ref))
    try:
        utc = (
            await client.get(
                "/v1/dashboard/stats", params={"period": "last_7_days"}, headers=seeded_calls.a.headers
            )
        ).json()
        ist = (
            await client.get(
                "/v1/dashboard/stats",
                params={"period": "last_7_days", "tz": "Asia/Kolkata"},
                headers=seeded_calls.a.headers,
            )
        ).json()
        next_day = (yesterday + timedelta(days=1)).isoformat()
        ist_day = next(s for s in ist["series"] if s["bucket_start"] == next_day)
        utc_day = next(s for s in utc["series"] if s["bucket_start"] == yesterday.isoformat())
        assert ist_day["total_calls"] >= 1 and utc_day["total_calls"] >= 1
    finally:
        owner_sql("update calls set created_at = %s where id = %s", (original, ref))


async def test_quality_empty_until_007(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    quality = (await client.get("/v1/dashboard/quality", params={"period": "last_7_days"}, headers=h)).json()
    assert quality["per_evaluator"] == [] and quality["total_calls_evaluated"] == 0
    assert quality["prior_window"]["to"] == quality["window"]["from"]
    health = (await client.get("/v1/dashboard/agent-health", headers=h)).json()
    assert health["items"] == []
