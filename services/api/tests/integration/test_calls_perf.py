"""Performance (006 T051, T086; SC-001, SC-002): call list first page p95 < 1.5 s and the 30-day
dashboard p95 < 2 s.

Calls are bulk-loaded as the owner into a fresh workspace, spread over the last 30 days.
``PERF_CALL_ROWS`` sets the size (default 100,000, the SC-002 window; use 1000000 for SC-001).
"""

from __future__ import annotations

import os
import statistics
import time

import psycopg
from fastapi import FastAPI

from app.dev.seed_calls import seed
from tests.conftest import make_client, signup
from tests.runtime_support import _owner_dsn

ROWS = int(os.environ.get("PERF_CALL_ROWS", "100000"))


def _bulk_load(workspace_id: str, agent_id: str, version_id: str, rows: int) -> None:
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        conn.execute(
            """
            insert into calls (id, workspace_id, agent_id, agent_version_id, origin, channel, direction,
                               from_number, status, disconnect_reason, created_at, billable_seconds,
                               cost_total_usd, sentiment, latency_stats)
            select 'call_' || upper(substr(md5(%(ws)s || g), 1, 26)), %(ws)s, %(agent)s, %(version)s,
                   (array['live','live','live','test'])[1 + g %% 4],
                   (array['web','sip_inbound','sip_outbound','whatsapp'])[1 + g %% 4],
                   'inbound', '+1555' || lpad((g %% 10000000)::text, 7, '0'),
                   (array['completed','completed','completed','failed','no_answer'])[1 + g %% 5],
                   'user_hangup', now() - (g %% 43200) * interval '1 minute', 30 + g %% 400,
                   round((0.01 + (g %% 500) / 1000.0)::numeric, 6),
                   (array['positive','neutral','negative','unknown'])[1 + g %% 4],
                   jsonb_build_object('e2e_avg_ms', 600 + g %% 900, 'turns', 4)
              from generate_series(1, %(n)s) g
            """,
            {"ws": workspace_id, "agent": agent_id, "version": version_id, "n": rows},
        )
        conn.execute("analyze calls")


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1]


async def test_list_and_dashboard_latency(app: FastAPI) -> None:
    async with make_client(app, ip="10.6.9.9") as client:
        account = await signup(client, app)
        with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
            data = seed(conn, account.workspace_id, calls=6)
        version = (
            psycopg.connect(_owner_dsn())
            .execute("select draft_version_id from agents where id = %s", (data.agent_ids[0],))
            .fetchone()
        )
        assert version is not None
        _bulk_load(account.workspace_id, data.agent_ids[0], version[0], ROWS)
        list_times: list[float] = []
        for params in (
            {},
            {"status": "failed"},
            {"channel": "whatsapp"},
            {"from_number": "+15550001"},
            {"sort": "cost_usd"},
        ) * 4:
            t0 = time.perf_counter()
            r = await client.get("/v1/calls", params=params, headers=account.headers)
            list_times.append(time.perf_counter() - t0)
            assert r.status_code == 200
        dash_times: list[float] = []
        for _ in range(10):
            t0 = time.perf_counter()
            r = await client.get(
                "/v1/dashboard/stats", params={"period": "last_30_days"}, headers=account.headers
            )
            dash_times.append(time.perf_counter() - t0)
            assert r.status_code == 200
    assert _p95(list_times) < 1.5, f"call list p95 {_p95(list_times):.2f}s"
    assert _p95(dash_times) < 2.0, f"dashboard p95 {_p95(dash_times):.2f}s"
