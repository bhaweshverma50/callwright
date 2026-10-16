"""contracts/agent_versions.yaml (T052, T089, T099)."""

from __future__ import annotations

import httpx

from app.agents import hooks
from tests.agent_helpers import create_ok, save_prompt
from tests.conftest import Account
from tests.contract.conftest import check

MISSING_AGENT = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MISSING_VERSION = "agv_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_list_and_get_200_401_404(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    await save_prompt(client, account, agent, "Second prompt.")
    listed = check(await client.get(f"/v1/agents/{agent['id']}/versions", headers=account.headers))
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [v["version_number"] for v in items] == [2, 1]
    assert items[0]["parent_version_number"] == 1 and items[1]["parent_version_number"] is None
    assert items[0]["is_draft"] and items[0]["summary"]["llm_model"] == "gpt-5.1"
    assert items[0]["created_by_email"] == account.email
    assert check(await client.get(f"/v1/agents/{agent['id']}/versions")).status_code == 401
    assert (
        check(await client.get(f"/v1/agents/{MISSING_AGENT}/versions", headers=account.headers)).status_code
        == 404
    )
    detail = check(
        await client.get(f"/v1/agents/{agent['id']}/versions/{items[1]['id']}", headers=account.headers)
    )
    assert detail.status_code == 200 and detail.json()["config"]["prompt"] == agent["draft_config"]["prompt"]
    assert check(await client.get(f"/v1/agents/{agent['id']}/versions/{items[1]['id']}")).status_code == 401
    missing = check(
        await client.get(f"/v1/agents/{agent['id']}/versions/{MISSING_VERSION}", headers=account.headers)
    )
    assert missing.status_code == 404


async def test_snapshot_blocks_in_version_detail(client: httpx.AsyncClient, account: Account) -> None:
    def tools(ctx: hooks.HookContext) -> list[dict[str, str]]:
        return [{"tool_id": t, "name": "lookup"} for t in ctx.config.get("tool_ids", [])]

    def knowledge(ctx: hooks.HookContext) -> list[dict[str, str]]:
        return [{"kb_id": k, "name": "FAQ"} for k in ctx.config.get("kb_ids", [])]

    with hooks.registered(resolvers={"tools": tools, "knowledge": knowledge}):
        agent = await create_ok(
            client, account, config={"prompt": "x", "tool_ids": ["tool_a"], "kb_ids": ["kb_a"]}
        )
    versions = (await client.get(f"/v1/agents/{agent['id']}/versions", headers=account.headers)).json()
    detail = check(
        await client.get(
            f"/v1/agents/{agent['id']}/versions/{versions['items'][0]['id']}", headers=account.headers
        )
    )
    assert detail.json()["config"]["tools"] == [{"tool_id": "tool_a", "name": "lookup"}]
    assert detail.json()["config"]["knowledge"] == [{"kb_id": "kb_a", "name": "FAQ"}]
    assert "tools" not in agent["draft_config"]


async def test_diff_200_404(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    saved = await save_prompt(client, account, agent, "Changed.")
    v1 = agent["draft_version"]["id"]
    v2 = saved["version"]["id"]
    response = check(
        await client.get(f"/v1/agents/{agent['id']}/versions/{v2}/diff?against={v1}", headers=account.headers)
    )
    assert response.status_code == 200
    assert response.json()["changes"] == [
        {"op": "replace", "path": "/prompt", "old": agent["draft_config"]["prompt"], "new": "Changed."}
    ]
    draft = check(
        await client.get(
            f"/v1/agents/{agent['id']}/versions/{v1}/diff?against=draft", headers=account.headers
        )
    )
    assert draft.json()["from"] == "draft" and len(draft.json()["changes"]) == 1
    missing = check(
        await client.get(
            f"/v1/agents/{agent['id']}/versions/{MISSING_VERSION}/diff?against=draft", headers=account.headers
        )
    )
    assert missing.status_code == 404


async def test_restore_200_404_412_422(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    saved = await save_prompt(client, account, agent, "Second.")
    v1 = agent["draft_version"]["id"]
    url = f"/v1/agents/{agent['id']}/versions/{v1}/restore"
    stale = check(await client.post(url, json={}, headers={**account.headers, "If-Match": '"1"'}))
    assert stale.status_code == 412
    restored = check(
        await client.post(url, json={"note": "roll back"}, headers={**account.headers, "If-Match": '"2"'})
    )
    assert restored.status_code == 200
    assert restored.json()["version"]["version_number"] == 3 and restored.headers["etag"] == '"3"'
    missing = check(
        await client.post(
            f"/v1/agents/{agent['id']}/versions/{MISSING_VERSION}/restore",
            json={},
            headers={**account.headers, "If-Match": '"3"'},
        )
    )
    assert missing.status_code == 404
    blocked = await create_ok(
        client, account, config={"prompt": "x", "llm": {"provider": "openai", "model": "gpt-5.2"}}
    )

    def blocker(ctx: hooks.HookContext) -> hooks.HookIssues:
        return hooks.HookIssues(
            publish_blockers=[{"pointer": "/tool_ids", "code": "missing_reference", "message": "x"}]
        )

    with hooks.registered(validators={"tool_ids": blocker}):
        refused = check(
            await client.post(
                f"/v1/agents/{blocked['id']}/versions/{blocked['draft_version']['id']}/restore",
                json={"publish": True},
                headers={**account.headers, "If-Match": '"1"'},
            )
        )
    assert refused.status_code == 422 and refused.json()["code"] == "publish_blocked"
    assert saved["created"]


async def test_publish_200_404_422_and_unpublish_204_404(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    url = f"/v1/agents/{agent['id']}/published-version"
    published = check(
        await client.put(url, json={"version_id": agent["draft_version"]["id"]}, headers=account.headers)
    )
    assert published.status_code == 200 and published.json()["published_version"]["version_number"] == 1
    missing = check(await client.put(url, json={"version_id": MISSING_VERSION}, headers=account.headers))
    assert missing.status_code == 404

    def blocker(ctx: hooks.HookContext) -> hooks.HookIssues:
        return hooks.HookIssues(
            publish_blockers=[{"pointer": "/kb_ids", "code": "missing_reference", "message": "x"}]
        )

    with hooks.registered(validators={"kb_ids": blocker}):
        refused = check(
            await client.put(url, json={"version_id": agent["draft_version"]["id"]}, headers=account.headers)
        )
    assert refused.status_code == 422 and refused.json()["code"] == "publish_blocked"
    assert refused.json()["errors"][0]["pointer"] == "/kb_ids"
    assert check(await client.delete(url, headers=account.headers)).status_code == 204
    assert (
        check(
            await client.delete(f"/v1/agents/{MISSING_AGENT}/published-version", headers=account.headers)
        ).status_code
        == 404
    )
