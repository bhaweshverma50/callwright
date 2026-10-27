"""Homepage playground: GET /v1/public/demo and POST /v1/public/demo-calls (contracts/demo.yaml)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import Runtime, owner_sql

URL = "/v1/public/demo-calls"


def switch_on(app: FastAPI, workspace_id: str, agents: str, per_hour: int = 3) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"demo_workspace_id": workspace_id, "demo_agents": agents, "demo_calls_per_hour": per_hour}
    )


async def test_off_by_default(client: httpx.AsyncClient) -> None:
    info = check(await client.get("/v1/public/demo"))
    assert info.status_code == 200 and info.json() == {"agents": []}
    refused = check(await client.post(URL, json={"agent": "clinic"}))
    assert refused.status_code == 404


async def test_visitor_calls_a_demo_agent_without_signing_in(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    clinic = runtime.versions.add_agent(account.workspace_id)
    roadside = runtime.versions.add_agent(account.workspace_id)
    switch_on(app, account.workspace_id, f"clinic={clinic.agent_id}, roadside={roadside.agent_id}")
    assert check(await client.get("/v1/public/demo")).json() == {"agents": ["clinic", "roadside"]}

    response = check(await client.post(URL, json={"agent": "clinic"}))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["room_name"] == f"call-{body['call_id']}"
    assert body["room_name"] in runtime.livekit.rooms
    rows = owner_sql(
        "select workspace_id, initiated_by_user_id, metadata->>'source' from calls where id = %s",
        (body["call_id"],),
    )
    assert rows == [(account.workspace_id, None, "homepage_playground")]

    unknown = check(await client.post(URL, json={"agent": "loan"}))
    assert unknown.status_code == 404
    bad = check(await client.post(URL, json={"agent": "Clinic!"}))
    assert bad.status_code == 422


async def test_each_visitor_gets_a_few_calls_an_hour(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    clinic = runtime.versions.add_agent(account.workspace_id)
    switch_on(app, account.workspace_id, f"clinic={clinic.agent_id}", per_hour=2)
    for _ in range(2):
        assert check(await client.post(URL, json={"agent": "clinic"})).status_code == 201
    limited = check(await client.post(URL, json={"agent": "clinic"}))
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited" and int(limited.headers["Retry-After"]) > 0
