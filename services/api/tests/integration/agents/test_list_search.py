"""Agent list and search (T046, FR-018, FR-019)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.agent_helpers import create_ok
from tests.conftest import Account, signup


async def names(client: httpx.AsyncClient, account: Account, query: str = "") -> list[str]:
    response = await client.get(f"/v1/agents?page_size=100{query}", headers=account.headers)
    assert response.status_code == 200
    return [a["name"] for a in response.json()["items"]]


async def test_search_filter_order_and_pages(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    clinic = await create_ok(client, account, name="Dental Clinic Desk")
    await create_ok(client, account, name="Roadside 100% help")
    flow = await create_ok(client, account, name="Clinic flow", agent_type="flow", config={"prompt": ""})
    assert await names(client, account) == ["Clinic flow", "Roadside 100% help", "Dental Clinic Desk"]
    assert await names(client, account, "&search=clinic") == ["Clinic flow", "Dental Clinic Desk"]
    assert await names(client, account, "&search=CLINIC&type=single_prompt") == ["Dental Clinic Desk"]
    assert await names(client, account, f"&search={clinic['id']}") == ["Dental Clinic Desk"]
    assert await names(client, account, "&search=100%25") == ["Roadside 100% help"]
    assert await names(client, account, "&search=_") == []
    assert await names(client, account, "&type=flow") == ["Clinic flow"]
    page = (await client.get("/v1/agents?page=2&page_size=2", headers=account.headers)).json()
    assert (
        page["total"] == 3
        and page["total_pages"] == 2
        and [a["name"] for a in page["items"]] == ["Dental Clinic Desk"]
    )
    # Renaming moves an agent to the top (newest updated first).
    await client.patch(
        f"/v1/agents/{clinic['id']}", json={"name": "Dental Clinic Desk 2"}, headers=account.headers
    )
    assert (await names(client, account))[0] == "Dental Clinic Desk 2"
    # Deleted agents are hidden from list and search.
    await client.delete(f"/v1/agents/{flow['id']}", headers=account.headers)
    assert "Clinic flow" not in await names(client, account, "&search=clinic")
    assert (await client.get(f"/v1/agents/{flow['id']}", headers=account.headers)).status_code == 404


async def test_list_shows_published_version(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account, name="Published one")
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": agent["draft_version"]["id"]},
        headers=account.headers,
    )
    items = (await client.get(f"/v1/agents?search={agent['id']}", headers=account.headers)).json()["items"]
    assert items[0]["published_version"]["version_number"] == 1
    assert items[0]["has_publish_blockers"] is False


async def test_other_workspace_agents_invisible(client: httpx.AsyncClient, app: FastAPI) -> None:
    a = await signup(client, app)
    b = await signup(client, app)
    agent = await create_ok(client, a, name="Private agent")
    assert await names(client, b, f"&search={agent['id']}") == []
    assert (await client.get(f"/v1/agents/{agent['id']}", headers=b.headers)).status_code == 404
