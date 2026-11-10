"""Performance smoke (T086): /v1/me and /v1/billing/balance p95 under 150 ms with 1M ledger rows.

The rows are bulk-loaded as the owner role into one workspace (the worst case for the
latest-row lookup) plus the caller's own workspace. Set ``PERF_LEDGER_ROWS`` to change the size.
"""

from __future__ import annotations

import os
import time

import httpx
import psycopg
from fastapi import FastAPI

from tests.conftest import PG, TEST_DB, make_workspace, signup
from tests.perf import SLACK

ROWS = int(os.environ.get("PERF_LEDGER_ROWS", "1000000"))


def _bulk_load(workspace_id: str, rows: int) -> None:
    with psycopg.connect(f"postgresql://callwright:callwright@{PG}/{TEST_DB}", autocommit=True) as conn:
        conn.execute(
            """
            insert into credit_transactions
              (id, workspace_id, seq, type, amount_usd, balance_after_usd, description, idempotency_key)
            select 'txn_' || upper(substr(md5(%(ws)s || g), 1, 26)), %(ws)s, g + 1, 'adjustment', 0.010000,
                   5 + g * 0.01, 'perf', 'perf-' || g
            from generate_series(1, %(n)s) g
            """,
            {"ws": workspace_id, "n": rows},
        )
        conn.execute("analyze credit_transactions")


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int(len(ordered) * 0.95) - 1]


async def test_me_and_balance_p95(client: httpx.AsyncClient, app: FastAPI) -> None:
    _, heavy = await make_workspace(app)
    _bulk_load(heavy, ROWS - 1)
    account = await signup(client, app)
    _bulk_load(account.workspace_id, 1000)
    timings: dict[str, list[float]] = {"/v1/me": [], "/v1/billing/balance": []}
    for _ in range(5):  # warm up
        await client.get("/v1/me", headers=account.headers)
    for _ in range(60):
        for path, samples in timings.items():
            start = time.perf_counter()
            response = await client.get(path, headers=account.headers)
            samples.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200
    balance = (await client.get("/v1/billing/balance", headers=account.headers)).json()
    assert balance["as_of_seq"] == 1001
    for path, samples in timings.items():
        assert _p95(samples) < 150 * SLACK, f"{path} p95 {_p95(samples):.1f} ms"
