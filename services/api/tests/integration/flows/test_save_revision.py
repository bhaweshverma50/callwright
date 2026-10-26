"""Draft saves with ``If-Match`` (004 T014; US1 scenario 7, FR-006, FR-007, research R2)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.flow_helpers import clinic, create_flow, save


async def test_save_then_stale_save_conflicts(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    first = await save(client, account, flow, clinic())
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 2 and first.headers["etag"] == '"2"'
    stale = await save(client, account, flow, clinic(), revision=1)
    assert stale.status_code == 412
    assert stale.json()["code"] == "flow_revision_conflict" and stale.json()["current_revision"] == 2


async def test_reload_restores_graph_positions_and_viewport(
    client: httpx.AsyncClient, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["viewport"] = {"x": -120.5, "y": 44, "zoom": 0.75}
    g["nodes"][3]["position"] = {"x": 1234.5, "y": -77}
    assert (await save(client, account, flow, g)).status_code == 200
    loaded = (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()
    assert loaded["graph"] == g


async def test_drafts_with_errors_are_saved(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"].append({**g["nodes"][0], "id": "n_start002"})
    response = await save(client, account, flow, g)
    assert response.status_code == 200
    assert response.json()["last_validation"]["errors"] >= 1


async def test_name_renames_the_agent(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    response = await save(client, account, flow, clinic(), name="Harbour clinic")
    assert response.status_code == 200 and response.json()["name"] == "Harbour clinic"
    agent = (await client.get(f"/v1/agents/{flow['agent_id']}", headers=account.headers)).json()
    assert agent["name"] == "Harbour clinic"


async def test_limits_are_refused(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    filler = g["nodes"][4]
    g["nodes"] += [{**filler, "id": f"n_x{i:07d}"} for i in range(195)]
    response = await save(client, account, flow, g)
    assert response.status_code == 422


async def test_secret_headers_never_come_back(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"][3]["config"]["request"]["headers"].append(
        {"name": "Authorization", "value": "Bearer sk-live-123456789", "secret": True}
    )
    saved = await save(client, account, flow, g)
    assert saved.status_code == 200, saved.text
    assert "sk-live-123456789" not in saved.text
    header = saved.json()["graph"]["nodes"][3]["config"]["request"]["headers"][1]
    assert header["secret_ref"].startswith("flow_hdr:") and header["masked_value"]
    # Sent back masked, the stored secret is kept.
    again = await save(client, account, saved.json(), saved.json()["graph"])
    assert again.status_code == 200
    assert (
        again.json()["graph"]["nodes"][3]["config"]["request"]["headers"][1]["secret_ref"]
        == header["secret_ref"]
    )
    preview = await client.post(f"/v1/flows/{flow['id']}/compile", headers=account.headers)
    assert "sk-live-123456789" not in preview.text
