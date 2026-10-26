"""Publish (004 T036; US2, FR-027 to FR-029, data-model section 5)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.flow_helpers import clinic, create_flow, save


async def test_publish_refuses_errors_and_stale_revisions(
    client: httpx.AsyncClient, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"].append({**g["nodes"][0], "id": "n_start002"})
    saved = (await save(client, account, flow, g)).json()
    refused = await client.post(
        f"/v1/flows/{flow['id']}/publish", json={"expected_revision": 2}, headers=account.headers
    )
    assert refused.status_code == 422 and refused.json()["code"] == "flow_has_errors"
    assert any(i["code"] == "E_START_COUNT" for i in refused.json()["issues"])
    stale = await client.post(
        f"/v1/flows/{flow['id']}/publish", json={"expected_revision": 1}, headers=account.headers
    )
    assert stale.status_code == 409 and stale.json()["current_revision"] == saved["revision"]


async def test_publish_records_a_version_with_the_compiled_flow(
    client: httpx.AsyncClient, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"].append(
        {"id": "n_island01", "type": "end", "label": "Island", "position": {"x": 0, "y": 900}, "config": {}}
    )
    assert (await save(client, account, flow, g)).status_code == 200
    response = await client.post(
        f"/v1/flows/{flow['id']}/publish",
        json={"expected_revision": 2, "release_notes": "First flow"},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["warnings"] >= 1 and len(body["graph_hash"]) == 64
    version = (
        await client.get(
            f"/v1/agents/{flow['agent_id']}/versions/{body['agent_version_id']}", headers=account.headers
        )
    ).json()
    block = version["config"]["flow"]
    assert block["graph"]["nodes"] == g["nodes"] and block["graph_hash"] == body["graph_hash"]
    assert block["compiled"]["entry_node_id"] == "n_start001"
    agent = (await client.get(f"/v1/agents/{flow['agent_id']}", headers=account.headers)).json()
    assert agent["published_version"]["id"] == body["agent_version_id"]
    reloaded = (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()
    assert reloaded["last_published_version_id"] == body["agent_version_id"]

    # Editing the draft afterwards leaves the published version untouched (FR-029).
    g["nodes"][1]["label"] = "Front door"
    assert (await save(client, account, reloaded, g)).status_code == 200
    again = (
        await client.get(
            f"/v1/agents/{flow['agent_id']}/versions/{body['agent_version_id']}", headers=account.headers
        )
    ).json()
    assert again["config"]["flow"]["graph"]["nodes"][1]["label"] == "Triage"


async def test_compile_preview(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    preview = (await client.post(f"/v1/flows/{flow['id']}/compile", headers=account.headers)).json()
    assert preview["ok"] is True and preview["compiled"]["schema_version"] == 1
    validate = await client.post(
        f"/v1/flows/{flow['id']}/validate",
        json={"graph": {**clinic(), "nodes": clinic()["nodes"][1:]}},
        headers=account.headers,
    )
    assert validate.status_code == 200 and validate.json()["errors"] >= 1
