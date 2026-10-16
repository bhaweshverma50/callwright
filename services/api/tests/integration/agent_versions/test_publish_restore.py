"""Publish, unpublish and restore (T054, FR-026, FR-027, US3)."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.llms import service as llm_service
from tests.agent_helpers import create_ok, save_prompt
from tests.conftest import Account


async def history(client: httpx.AsyncClient, account: Account, agent_id: str) -> list[dict]:  # type: ignore[type-arg]
    items: list[dict] = (  # type: ignore[type-arg]
        await client.get(f"/v1/agents/{agent_id}/versions", headers=account.headers)
    ).json()["items"]
    return items


async def publish(
    client: httpx.AsyncClient, account: Account, agent_id: str, version_id: str
) -> httpx.Response:
    return await client.put(
        f"/v1/agents/{agent_id}/published-version", json={"version_id": version_id}, headers=account.headers
    )


async def test_quickstart_story(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    v2 = await save_prompt(client, account, agent, "Prompt two.")
    v3 = await save_prompt(client, account, v2["agent"], "Prompt three.")
    v1_id, v2_id = agent["draft_version"]["id"], v2["version"]["id"]
    diff = (
        await client.get(
            f"/v1/agents/{agent['id']}/versions/{v3['version']['id']}/diff?against={v1_id}",
            headers=account.headers,
        )
    ).json()
    assert [c["path"] for c in diff["changes"]] == ["/prompt"]
    published = await publish(client, account, agent["id"], v2_id)
    assert published.status_code == 200 and published.json()["published_version"]["id"] == v2_id
    restored = await client.post(
        f"/v1/agents/{agent['id']}/versions/{v1_id}/restore",
        json={"note": "roll back"},
        headers={**account.headers, "If-Match": f'"{v3["agent"]["draft_revision"]}"'},
    )
    assert restored.status_code == 200
    body = restored.json()
    assert body["version"]["version_number"] == 4
    assert body["agent"]["published_version"]["id"] == v2_id
    assert body["agent"]["draft_config"]["prompt"] == agent["draft_config"]["prompt"]
    items = await history(client, account, agent["id"])
    assert [v["version_number"] for v in items] == [4, 3, 2, 1]
    newest = items[0]
    assert newest["source"] == "restore" and newest["restored_from_version_number"] == 1
    assert newest["note"] == "roll back" and newest["parent_version_number"] == 3 and newest["is_draft"]
    assert [v["is_published"] for v in items] == [False, False, True, False]


async def test_restore_and_publish(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    v2 = await save_prompt(client, account, agent, "Two.")
    restored = await client.post(
        f"/v1/agents/{agent['id']}/versions/{agent['draft_version']['id']}/restore",
        json={"publish": True},
        headers={**account.headers, "If-Match": '"2"'},
    )
    assert restored.status_code == 200
    body = restored.json()
    assert body["agent"]["published_version"]["id"] == body["version"]["id"]
    assert (await history(client, account, agent["id"]))[0]["note"] == "Restored from version 1"
    assert v2["created"]


async def test_publish_rechecks_blockers_against_current_catalog(
    client: httpx.AsyncClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await create_ok(
        client, account, config={"prompt": "x", "llm": {"provider": "openai", "model": "gpt-5.2"}}
    )
    assert agent["publish_blockers"] == []
    catalog = llm_service.load_catalog()
    withdrawn = replace(
        catalog, models=tuple(replace(m, withdrawn=m.id == "gpt-5.2") for m in catalog.models)
    )
    monkeypatch.setattr(llm_service, "load_catalog", lambda: withdrawn)
    import app.agents.validation as validation

    monkeypatch.setattr(validation, "load_llm_catalog", lambda: withdrawn)
    refused = await publish(client, account, agent["id"], agent["draft_version"]["id"])
    assert refused.status_code == 422 and refused.json()["code"] == "publish_blocked"
    assert refused.json()["errors"] == [
        {
            "pointer": "/llm/model",
            "code": "withdrawn",
            "message": "GPT-5.2 is no longer offered. Choose another model.",
        }
    ]


async def test_unpublish(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    await publish(client, account, agent["id"], agent["draft_version"]["id"])
    assert (
        await client.delete(f"/v1/agents/{agent['id']}/published-version", headers=account.headers)
    ).status_code == 204
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert detail["published_version"] is None


async def test_restore_with_stale_revision(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    await save_prompt(client, account, agent, "Two.")
    stale = await client.post(
        f"/v1/agents/{agent['id']}/versions/{agent['draft_version']['id']}/restore",
        json={},
        headers={**account.headers, "If-Match": '"1"'},
    )
    assert stale.status_code == 412 and stale.json()["current_revision"] == 2
    assert len(await history(client, account, agent["id"])) == 2


async def test_versions_of_a_deleted_agent_are_readable(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)
    items = await history(client, account, agent["id"])
    assert [v["version_number"] for v in items] == [1]
    assert (await publish(client, account, agent["id"], agent["draft_version"]["id"])).status_code == 404


async def test_version_of_another_agent_is_404(client: httpx.AsyncClient, account: Account) -> None:
    a = await create_ok(client, account, name="A")
    b = await create_ok(client, account, name="B")
    assert (await publish(client, account, a["id"], b["draft_version"]["id"])).status_code == 404
    got = await client.get(
        f"/v1/agents/{a['id']}/versions/{b['draft_version']['id']}", headers=account.headers
    )
    assert got.status_code == 404
