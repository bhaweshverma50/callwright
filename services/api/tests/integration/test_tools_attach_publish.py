"""Attach, publish, edit and delete (005 T017): published versions embed resolved tools."""

from __future__ import annotations

import httpx

from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.contract.test_tools_contract import end_call, http_tool, make


async def _version_config(
    client: httpx.AsyncClient, account: Account, agent_id: str, version_id: str
) -> dict:
    response = await client.get(f"/v1/agents/{agent_id}/versions/{version_id}", headers=account.headers)
    assert response.status_code == 200, response.text
    config: dict = response.json()["config"]
    return config


async def test_publish_embeds_tool_spec_and_edits_do_not_leak(
    client: httpx.AsyncClient, account: Account
) -> None:
    secret = "Bearer live-secret-0042"
    tool = await make(
        client, account, http_tool(headers=[{"name": "Authorization", "value": secret, "secret": True}])
    )
    agent = await create_ok(client, account)
    await client.put(
        f"/v1/agents/{agent['id']}/tools", json={"tool_ids": [tool["id"]]}, headers=account.headers
    )
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    version_id = detail["draft_version"]["id"]
    published = await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": version_id},
        headers=account.headers,
    )
    assert published.status_code == 200, published.text

    config = await _version_config(client, account, agent["id"], version_id)
    [spec] = config["tools"]
    assert spec["tool_id"] == tool["id"] and spec["name"] == "check_availability"
    header = spec["config"]["headers"][0]
    assert header == {"name": "Authorization", "secret": True, "secret_ref": header["secret_ref"]}
    assert secret not in str(config) and "masked_value" not in str(config)

    edited = await client.patch(
        f"/v1/tools/{tool['id']}", json={"description": "Changed description"}, headers=account.headers
    )
    assert edited.status_code == 200
    again = await _version_config(client, account, agent["id"], version_id)
    assert again["tools"][0]["description"] == "Look up slots", "published version must not change"

    usages = (await client.get(f"/v1/tools/{tool['id']}/usages", headers=account.headers)).json()["items"]
    assert usages[0]["published_version_ids"] == [version_id]


async def test_force_delete_detaches_drafts_only(client: httpx.AsyncClient, account: Account) -> None:
    tool = await make(client, account, end_call())
    agent = await create_ok(client, account)
    await client.put(
        f"/v1/agents/{agent['id']}/tools", json={"tool_ids": [tool["id"]]}, headers=account.headers
    )
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    version_id = detail["draft_version"]["id"]
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": version_id},
        headers=account.headers,
    )
    deleted = await client.delete(f"/v1/tools/{tool['id']}?force=true", headers=account.headers)
    assert deleted.json()["detached_agent_ids"] == [agent["id"]]
    after = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert after["draft_config"]["tool_ids"] == []
    assert after["published_version"]["id"] == version_id
    published = await _version_config(client, account, agent["id"], version_id)
    assert [t["tool_id"] for t in published["tools"]] == [tool["id"]]
