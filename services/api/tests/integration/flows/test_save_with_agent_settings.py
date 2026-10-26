"""Atomic save of graph and flow-wide settings (004 T102; FR-046, FR-048, data-model 9)."""

from __future__ import annotations

from typing import Any

import httpx

from tests.conftest import Account
from tests.flow_helpers import clinic, create_flow, save


async def _setup(client: httpx.AsyncClient, account: Account) -> tuple[dict[str, Any], dict[str, Any]]:
    flow = (await create_flow(client, account))["flow"]
    agent = (await client.get(f"/v1/agents/{flow['agent_id']}", headers=account.headers)).json()
    return flow, agent


async def test_graph_and_settings_saved_together(client: httpx.AsyncClient, account: Account) -> None:
    flow, agent = await _setup(client, account)
    settings = {
        "expected_draft_revision": flow["agent_draft_revision"],
        "changes": {"prompt": "You are Harbour Clinic's receptionist."},
    }
    response = await save(client, account, flow, clinic(), agent_settings=settings)
    assert response.status_code == 200, response.text
    assert response.json()["agent_draft_revision"] == flow["agent_draft_revision"] + 1
    after = (await client.get(f"/v1/agents/{flow['agent_id']}", headers=account.headers)).json()
    assert after["draft_config"]["prompt"] == "You are Harbour Clinic's receptionist."
    assert after["draft_config"]["call_behavior"] == agent["draft_config"]["call_behavior"]
    assert after["draft_config"]["advanced"] == agent["draft_config"]["advanced"]


async def test_stale_settings_revision_stores_nothing(client: httpx.AsyncClient, account: Account) -> None:
    flow, _ = await _setup(client, account)
    settings = {"expected_draft_revision": flow["agent_draft_revision"] + 5, "changes": {"prompt": "x"}}
    response = await save(client, account, flow, clinic(), agent_settings=settings)
    assert response.status_code == 412 and response.json()["code"] == "agent_draft_changed"
    unchanged = (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()
    assert unchanged["revision"] == 1 and unchanged["graph"] == flow["graph"]


async def test_start_speaker_is_owned_by_the_start_node(client: httpx.AsyncClient, account: Account) -> None:
    flow, _ = await _setup(client, account)
    settings = {"expected_draft_revision": flow["agent_draft_revision"], "changes": {"start_speaker": "user"}}
    response = await save(client, account, flow, clinic(), agent_settings=settings)
    assert response.status_code == 422
    assert (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()["revision"] == 1


async def test_invalid_settings_roll_back_the_graph(client: httpx.AsyncClient, account: Account) -> None:
    flow, _ = await _setup(client, account)
    settings = {
        "expected_draft_revision": flow["agent_draft_revision"],
        "changes": {"call_behavior": {"max_duration_s": -5}},
    }
    response = await save(client, account, flow, clinic(), agent_settings=settings)
    assert response.status_code == 422, response.text
    assert (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()["revision"] == 1


async def test_rename_with_settings(client: httpx.AsyncClient, account: Account) -> None:
    flow, _ = await _setup(client, account)
    settings = {"expected_draft_revision": flow["agent_draft_revision"], "changes": {"prompt": "Be kind."}}
    response = await save(client, account, flow, clinic(), name="Renamed", agent_settings=settings)
    assert response.status_code == 200
    agent = (await client.get(f"/v1/agents/{flow['agent_id']}", headers=account.headers)).json()
    assert agent["name"] == "Renamed"
