"""contracts/agents.yaml: list, duplicate, delete (T045)."""

from __future__ import annotations

import httpx

from app.agents import hooks
from tests.agent_helpers import create_ok, save_prompt
from tests.conftest import Account
from tests.contract.conftest import check

MISSING_AGENT = "/v1/agents/agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_list_200_401(client: httpx.AsyncClient, account: Account) -> None:
    await create_ok(client, account, name="Listed one")
    response = check(
        await client.get("/v1/agents?page=1&page_size=5&type=single_prompt", headers=account.headers)
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["llm_model"] == "azure_openai/gpt-5.1" and item["voice_label"]
    assert check(await client.get("/v1/agents")).status_code == 401


async def test_list_status_counts_and_sort(client: httpx.AsyncClient, account: Account) -> None:
    live = await create_ok(client, account, name="b live")
    await create_ok(client, account, name="A draft")
    put = await client.put(
        f"/v1/agents/{live['id']}/published-version",
        json={"version_id": live["draft_version"]["id"]},
        headers=account.headers,
    )
    assert put.status_code == 200, put.text
    everything = check(await client.get("/v1/agents?sort=name", headers=account.headers)).json()
    assert everything["counts"] == {"all": 2, "live": 1, "draft": 1, "attention": 0}
    assert [a["name"] for a in everything["items"]] == ["A draft", "b live"]
    only_live = check(await client.get("/v1/agents?status=live", headers=account.headers)).json()
    assert [a["id"] for a in only_live["items"]] == [live["id"]] and only_live["total"] == 1
    assert only_live["counts"]["all"] == 2
    bad = await client.get("/v1/agents?status=nope", headers=account.headers)
    assert bad.status_code == 422


async def test_duplicate_a_saved_version(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    first = agent["draft_version"]["id"]
    await save_prompt(client, account, agent, "Second prompt, newer than version 1.")
    copy = check(
        await client.post(
            f"/v1/agents/{agent['id']}/duplicate", json={"version_id": first}, headers=account.headers
        )
    )
    assert copy.status_code == 201
    assert copy.json()["draft_config"]["prompt"] == agent["draft_config"]["prompt"]
    other = await create_ok(client, account, name="Other")
    foreign = await client.post(
        f"/v1/agents/{other['id']}/duplicate", json={"version_id": first}, headers=account.headers
    )
    assert foreign.status_code == 404


async def test_duplicate_201_404(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    copy = check(await client.post(f"/v1/agents/{agent['id']}/duplicate", headers=account.headers))
    assert copy.status_code == 201 and copy.json()["name"] == "Clinic desk (copy)"
    named = check(
        await client.post(
            f"/v1/agents/{agent['id']}/duplicate", json={"name": "Variant"}, headers=account.headers
        )
    )
    assert named.json()["name"] == "Variant"
    assert check(await client.post(f"{MISSING_AGENT}/duplicate", headers=account.headers)).status_code == 404


async def test_delete_204_404_409(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    busy = await create_ok(client, account, name="Busy")

    def checker(ctx: hooks.UsageContext) -> list[hooks.Attachment]:
        if ctx.agent_id == busy["id"]:
            return [hooks.Attachment("phone_number", "num_1", "+1 415 555 0100")]
        return []

    with hooks.registered(usage_checkers=[checker]):
        in_use = check(await client.delete(f"/v1/agents/{busy['id']}", headers=account.headers))
        assert in_use.status_code == 409
        assert in_use.json()["code"] == "agent_in_use"
        assert in_use.json()["attachments"] == [
            {"kind": "phone_number", "id": "num_1", "label": "+1 415 555 0100"}
        ]
        assert (
            check(await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)).status_code
            == 204
        )
    assert check(await client.delete(MISSING_AGENT, headers=account.headers)).status_code == 404
