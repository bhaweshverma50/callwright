"""contracts/flows.yaml: create, read, save and read-by-agent (004 T011, T114)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.flows.schemas import NODE_TYPES
from app.tools.schemas import TransferSpec, config_defaults
from tests.agent_helpers import create_ok
from tests.conftest import Account, signup
from tests.contract.conftest import check
from tests.flow_helpers import clinic, create_flow, save

MISSING_FLOW = "flw_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_create_and_read(client: httpx.AsyncClient, account: Account) -> None:
    created = check(
        await client.post("/v1/flows", json={"name": "Clinic", "language": "en-US"}, headers=account.headers)
    )
    assert created.status_code == 201 and created.headers["etag"] == '"1"'
    flow = created.json()["flow"]
    assert check(await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).status_code == 200
    by_agent = check(await client.get(f"/v1/agents/{flow['agent_id']}/flow", headers=account.headers))
    assert by_agent.status_code == 200


async def test_save_and_conflict(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    assert check(await save(client, account, flow, clinic())).status_code == 200
    conflict = check(await save(client, account, flow, clinic(), revision=1))
    assert conflict.status_code == 412
    settings = {"expected_draft_revision": 99, "changes": {"prompt": "x"}}
    stale = check(await save(client, account, {**flow, "revision": 2}, clinic(), agent_settings=settings))
    assert stale.status_code == 412 and stale.json()["code"] == "agent_draft_changed"


async def test_overrides_out_of_range_save_as_issues(client: httpx.AsyncClient, account: Account) -> None:
    """T114: node overrides are checked against 002's controls table; a draft with a bad value
    still saves and reports the field."""
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"][1]["config"]["overrides"]["tts"] = {"provider": "elevenlabs", "voice_id": "x", "speed": 5}
    saved = check(await save(client, account, flow, g))
    assert saved.status_code == 200
    issues = saved.json()["last_validation"]["issues"]
    assert any(i["field"] == "overrides.tts.speed" and i["code"] == "E_INVALID_FIELD" for i in issues)


async def test_errors(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    assert check(await client.get(f"/v1/flows/{MISSING_FLOW}", headers=account.headers)).status_code == 404
    assert (
        check(
            await client.post("/v1/flows", json={"name": "", "language": "en-US"}, headers=account.headers)
        ).status_code
        == 422
    )
    flow = (await create_flow(client, account))["flow"]
    bad = check(
        await save(client, account, flow, {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}})
    )
    assert bad.status_code == 422
    single = await create_ok(client, account)
    assert (
        check(await client.get(f"/v1/agents/{single['id']}/flow", headers=account.headers)).status_code == 409
    )
    other = await signup(client, app)
    assert check(await save(client, other, flow, clinic())).status_code == 404


async def test_node_defaults(client: httpx.AsyncClient, account: Account) -> None:
    """The builder's starting configs; requests and transfers carry the tool schemas' defaults."""
    response = check(await client.get("/v1/flows/node-defaults", headers=account.headers))
    assert response.status_code == 200
    by_type = {n["type"]: n for n in response.json()["node_types"]}
    assert list(by_type) == list(NODE_TYPES)
    assert by_type["start"]["label"] == "Start"
    assert by_type["transfer"]["config"]["transfer"] == config_defaults(TransferSpec)
    request = by_type["webhook"]["config"]["request"]
    assert request["speak_during_execution"] is True and request["url"] == ""
    assert check(await client.get("/v1/flows/node-defaults")).status_code == 401
