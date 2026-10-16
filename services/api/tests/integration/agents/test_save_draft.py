"""Draft saves (T028, FR-013, FR-015, FR-022, FR-023, SC-004)."""

from __future__ import annotations

import copy

import httpx

from tests.agent_helpers import create, create_ok, save
from tests.conftest import Account


async def versions(client: httpx.AsyncClient, account: Account, agent_id: str) -> list[dict]:  # type: ignore[type-arg]
    response = await client.get(f"/v1/agents/{agent_id}/versions", headers=account.headers)
    items: list[dict] = response.json()["items"]  # type: ignore[type-arg]
    return items


async def test_create_requires_a_valid_config(client: httpx.AsyncClient, account: Account) -> None:
    response = await create(
        client,
        account,
        name="x",
        config={"prompt": "", "tts": {"voice_id": ""}, "advanced": {"webhook_url": "ftp://x"}},
    )
    assert response.status_code == 422
    pointers = {e["pointer"] for e in response.json()["errors"]}
    assert {"/prompt", "/tts/voice_id", "/advanced/webhook_url"} <= pointers
    listed = await client.get("/v1/agents?search=x", headers=account.headers)
    assert all(a["name"] != "x" for a in listed.json()["items"])


async def test_quickstart_create_then_save(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account, config={"prompt": "You answer calls for a dental clinic."})
    assert agent["draft_version"]["version_number"] == 1 and agent["draft_revision"] == 1
    config = copy.deepcopy(agent["draft_config"])
    config["prompt"] = "Hello {{customer_name}}."
    config["dynamic_variables"] = [{"name": "customer_name", "default": "there"}]
    config["advanced"]["webhook_url"] = "https://hooks.example.com/clinic"
    first = await save(client, account, agent, config, note="first prompt")
    assert first.status_code == 200
    body = first.json()
    assert body["created"] is True and body["version"]["version_number"] == 2
    assert body["agent"]["draft_revision"] == 2
    again = await save(client, account, body["agent"], config)
    assert again.json()["created"] is False and again.json()["version"]["version_number"] == 2
    assert again.headers["etag"] == '"2"'
    stale = await save(client, account, agent, config, revision=1)
    assert stale.status_code == 412 and stale.json()["code"] == "draft_changed"
    reloaded = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert reloaded["draft_config"]["advanced"]["webhook_url"] == "https://hooks.example.com/clinic"
    assert [v["note"] for v in await versions(client, account, agent["id"])] == ["first prompt", None]


async def test_name_only_change_records_no_version(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    response = await save(client, account, agent, agent["draft_config"], name="Renamed desk")
    assert response.status_code == 200
    assert response.json()["created"] is False and response.json()["agent"]["name"] == "Renamed desk"
    assert len(await versions(client, account, agent["id"])) == 1


async def test_all_errors_returned_together(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    config = copy.deepcopy(agent["draft_config"])
    config["prompt"] = ""
    config["tts"]["voice_id"] = ""
    config["call_behavior"]["max_duration_s"] = 12
    config["call_behavior"]["ring_duration_ms"] = -1
    config["advanced"]["webhook_url"] = "notaurl"
    config["advanced"]["webhook_timeout_ms"] = 50
    response = await save(client, account, agent, config)
    assert response.status_code == 422
    assert {e["pointer"] for e in response.json()["errors"]} == {
        "/prompt",
        "/tts/voice_id",
        "/call_behavior/max_duration_s",
        "/call_behavior/ring_duration_ms",
        "/advanced/webhook_url",
        "/advanced/webhook_timeout_ms",
    }
    after = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert after["draft_revision"] == 1


async def test_private_webhook_host_refused(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    config = copy.deepcopy(agent["draft_config"])
    config["advanced"]["webhook_url"] = "https://private.test.example/hook"
    response = await save(client, account, agent, config)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "private_address"


async def test_snapshot_only_blocks_are_ignored_on_save(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    config = {**agent["draft_config"], "tools": [{"tool_id": "tool_x"}]}
    response = await save(client, account, agent, config)
    assert response.status_code == 200 and response.json()["created"] is False
    assert "tools" not in response.json()["agent"]["draft_config"]


async def test_type_is_immutable(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    config = {**agent["draft_config"], "type": "flow"}
    response = await save(client, account, agent, config)
    assert response.status_code == 200
    assert response.json()["agent"]["type"] == "single_prompt"
    assert response.json()["agent"]["draft_config"]["type"] == "single_prompt"
