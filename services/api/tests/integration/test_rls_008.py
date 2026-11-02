"""Tenancy of 008 (T086): every table refuses rows of another workspace, every endpoint answers
404 (or an empty list) for another workspace's records, and the internal endpoints derive the
workspace from the run, never from the request."""

from __future__ import annotations

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from tests.conftest import Account, make_client, signup
from tests.runtime_support import SERVICE_HEADERS, idem, owner_sql
from tests.sim_support import SimEnv, make_agent, seed_live_call

TABLES = (
    "test_categories",
    "test_cases",
    "test_runs",
    "test_results",
    "simulation_experiments",
    "simulation_runs",
    "datasets",
    "dataset_items",
)


def test_every_008_table_forces_rls() -> None:
    rows = owner_sql(
        "select relname, relrowsecurity, relforcerowsecurity from pg_class where relname = any(%s)",
        (list(TABLES),),
    )
    assert {r[0] for r in rows} == set(TABLES)
    assert all(r[1] and r[2] for r in rows)


async def test_cross_workspace_access_is_denied(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    calls = [seed_live_call(account.workspace_id, agent) for _ in range(2)]
    case = (
        await client.post(
            "/v1/test-cases",
            json={
                "agent_id": agent.agent_id,
                "category": "identity",
                "user_prompt": "a",
                "expected_behaviour": "b",
            },
            headers=h,
        )
    ).json()
    run = (
        await client.post("/v1/test-runs", json={"agent_id": agent.agent_id}, headers={**h, **idem()})
    ).json()
    srun = (
        await client.post(
            "/v1/simulation-runs",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_id": calls[0]},
            headers={**h, **idem()},
        )
    ).json()
    exp = (
        await client.post(
            "/v1/experiments",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls},
            headers={**h, **idem()},
        )
    ).json()
    ds = (
        await client.post("/v1/datasets", json={"name": "Mine", "agent_id": agent.agent_id}, headers=h)
    ).json()
    await sim_env.drain()

    async with make_client(app, ip="10.8.0.2") as other_client:
        intruder = await signup(other_client, app)
    bh = intruder.headers
    for path in (
        f"/v1/test-cases/{case['test_case_id']}",
        f"/v1/test-runs/{run['test_run_id']}",
        f"/v1/test-runs/{run['test_run_id']}/export",
        f"/v1/simulation-runs/{srun['simulation_run_id']}",
        f"/v1/simulation-runs/{srun['simulation_run_id']}/comparison",
        f"/v1/experiments/{exp['experiment_id']}",
        f"/v1/experiments/{exp['experiment_id']}/runs",
        f"/v1/experiments/{exp['experiment_id']}/scorecard",
        f"/v1/datasets/{ds['dataset_id']}",
        f"/v1/datasets/{ds['dataset_id']}/items",
    ):
        response = await client.get(path, headers=bh)
        assert response.status_code == 404, path
    for path in (
        f"/v1/test-cases?agent_id={agent.agent_id}",
        f"/v1/test-runs?agent_id={agent.agent_id}",
        f"/v1/simulation-runs?agent_id={agent.agent_id}",
        "/v1/simulation-runs",
        "/v1/experiments",
        "/v1/datasets",
    ):
        assert (await client.get(path, headers=bh)).json()["total"] == 0, path
    for method, path, body in (
        ("patch", f"/v1/test-cases/{case['test_case_id']}", {"name": "x"}),
        ("delete", f"/v1/test-cases/{case['test_case_id']}", None),
        ("post", f"/v1/experiments/{exp['experiment_id']}/cancel", None),
        ("post", f"/v1/simulation-runs/{srun['simulation_run_id']}/cancel", None),
        ("delete", f"/v1/datasets/{ds['dataset_id']}", None),
        ("post", f"/v1/datasets/{ds['dataset_id']}/items", {"call_ids": calls}),
    ):
        response = await client.request(method, path, json=body, headers=bh)
        assert response.status_code == 404, (method, path)
    # Using another workspace's calls or agent is refused, never silently accepted.
    theirs = await client.post(
        "/v1/simulation-runs",
        json={"agent_id": agent.agent_id, "mode": "replay", "base_call_id": calls[0]},
        headers={**bh, **idem()},
    )
    assert theirs.status_code == 422
    mine = await make_agent(client, intruder)
    stolen = await client.post(
        "/v1/experiments",
        json={"agent_id": mine.agent_id, "mode": "replay", "base_call_ids": calls},
        headers={**bh, **idem()},
    )
    assert stolen.status_code == 422
    # Internal endpoints: the run decides the workspace; a closed or unknown run is refused.
    spec = await client.get(
        f"/v1/internal/simulation-runs/{srun['simulation_run_id']}/spec", headers=SERVICE_HEADERS
    )
    assert spec.status_code == 409 and "workspace_id" not in spec.json()
    assert (
        await client.get(f"/v1/internal/simulation-runs/{srun['simulation_run_id']}/spec", headers=bh)
    ).status_code == 401


def test_app_role_cannot_write_into_another_workspace(account: Account) -> None:
    from tests.conftest import PG, TEST_DB

    with psycopg.connect(
        f"postgresql://callwright_app:callwright_app@{PG}/{TEST_DB}", autocommit=True
    ) as conn:
        conn.execute("select set_config('app.workspace_id', 'ws_somebody_else', false)")
        for table in TABLES:
            assert conn.execute(f"select count(*) from {table}").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "insert into test_categories (workspace_id, slug, name, color) "
                "values (%s, 'x_x', 'X', '#64748b')",
                (account.workspace_id,),
            )
