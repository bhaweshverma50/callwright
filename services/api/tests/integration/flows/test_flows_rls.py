"""Tenancy (004 T006): workspace B cannot read or write workspace A's flow."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account, signup
from tests.flow_helpers import clinic, create_flow, save


async def test_other_workspace_sees_nothing(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    other = await signup(client, app)
    assert (await client.get(f"/v1/flows/{flow['id']}", headers=other.headers)).status_code == 404
    assert (await client.get(f"/v1/agents/{flow['agent_id']}/flow", headers=other.headers)).status_code == 404
    assert (await save(client, other, flow, clinic())).status_code == 404
    publish = await client.post(
        f"/v1/flows/{flow['id']}/publish", json={"expected_revision": 1}, headers=other.headers
    )
    assert publish.status_code == 404
    assert (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()["revision"] == 1
