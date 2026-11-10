"""Calibration and review latency (007 T069): p95 under 1 s with 10,000 labelled calls."""

from __future__ import annotations

import statistics
import time

import httpx
import psycopg

from tests.conftest import Account
from tests.perf import SLACK
from tests.quality_support import seed_agent
from tests.runtime_support import _owner_dsn

N = 10_000


def bulk_seed(ws: str, user: str) -> None:
    agent, version = seed_agent(ws)
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        conn.execute(
            """
            insert into calls (id, workspace_id, agent_id, agent_version_id, origin, channel,
                direction, status,
                               created_at, connected_at, ended_at, completed_at, billable_seconds,
                                   pipeline_status)
            select 'call_PERF' || lpad(g::text, 22, '0'), %s, %s, %s, 'live', 'web', 'inbound', 'completed',
                   now() - make_interval(mins => g), now() - make_interval(mins => g),
                       now() - make_interval(mins => g),
                   now() - make_interval(mins => g), 60, 'done'
              from generate_series(1, %s) g
            """,
            (ws, agent, version, N + 2000),
        )
        conn.execute(
            """
            insert into evaluator_run_groups (run_group_id, workspace_id, call_id, trigger,
                idempotency_key, status)
            select 'erg_' || c.id, c.workspace_id, c.id, 'pipeline', 'pipeline',
                'done' from calls c where c.workspace_id = %s
            """,
            (ws,),
        )
        for name in ("intent_fulfillment", "latency_slo", "audio_silence"):
            from app.evaluators.registry import builtin_id

            conn.execute(
                """
                insert into evaluator_runs (id, workspace_id, call_id, agent_id, evaluator_id,
                    evaluator_version,
                                            run_group_id, trigger, settings_hash, status, verdict,
                                                score, rationale,
                                            completed_at)
                select 'evr_' || md5(c.id || %s), c.workspace_id, c.id, c.agent_id, %s, 1,
                    'erg_' || c.id, 'pipeline',
                       'h', 'completed', case when random() < 0.3 then 'fail' else 'pass' end,
                           random(), 'seeded', now()
                  from calls c where c.workspace_id = %s
                """,
                (name, builtin_id(name), ws),
            )
        conn.execute(
            """
            insert into annotations (id, workspace_id, call_id, user_id, label)
            select 'ann_' || substr(c.id, 6), c.workspace_id, c.id, %s,
                   case when random() < 0.7 then 'good' else 'bad' end
              from (select id, workspace_id from calls where workspace_id = %s order by id limit %s) c
            """,
            (user, ws, N),
        )
        conn.execute("analyze calls; analyze evaluator_runs; analyze annotations")


async def p95(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], params: dict[str, str] | None = None
) -> float:
    await client.get(url, params=params, headers=headers)  # warm-up: first request pays setup
    times = []
    for _ in range(12):
        start = time.perf_counter()
        r = await client.get(url, params=params, headers=headers)
        times.append(time.perf_counter() - start)
        assert r.status_code == 200, r.text
    return statistics.quantiles(times, n=20)[18]


async def test_calibration_and_review_p95(client: httpx.AsyncClient, account: Account) -> None:
    bulk_seed(account.workspace_id, account.user_id)
    h = account.headers
    for url, params in (
        ("/v1/calibration/evaluators", None),
        ("/v1/calibration/summary", None),
        ("/v1/review/queue", {"strategy": "random"}),
        ("/v1/review/queue", {"strategy": "disagreement"}),
        ("/v1/review/queue/summary", None),
    ):
        took = await p95(client, url, h, params)
        assert took < 1.0 * SLACK, f"{url} {params} p95 {took:.3f}s"
    rows = (await client.get("/v1/calibration/evaluators", headers=h)).json()["items"]
    assert sum(r["n"] for r in rows if r["flow_node_id"] is None) == 3 * N
