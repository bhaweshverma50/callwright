"""Duplicate and delete (T047, FR-020, FR-021, R14, R15)."""

from __future__ import annotations

import httpx

from app.agents import hooks
from tests.agent_helpers import create_ok, save_prompt
from tests.conftest import Account


async def test_duplicate_copies_draft_without_history(client: httpx.AsyncClient, account: Account) -> None:
    calls: list[hooks.DuplicateContext] = []

    async def on_duplicate(ctx: hooks.DuplicateContext) -> None:
        calls.append(ctx)

    agent = await create_ok(client, account, name="Original " + "x" * 70)
    saved = await save_prompt(client, account, agent, "Second prompt.")
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": saved["version"]["id"]},
        headers=account.headers,
    )
    with hooks.registered(duplicate_hooks=[on_duplicate]):
        response = await client.post(f"/v1/agents/{agent['id']}/duplicate", headers=account.headers)
    assert response.status_code == 201
    copy = response.json()
    assert copy["name"].endswith(" (copy)") and len(copy["name"]) <= 80
    assert copy["type"] == "single_prompt" and copy["draft_config"]["prompt"] == "Second prompt."
    assert copy["published_version"] is None and copy["draft_version"]["version_number"] == 1
    history = (await client.get(f"/v1/agents/{copy['id']}/versions", headers=account.headers)).json()
    assert history["total"] == 1 and history["items"][0]["source"] == "duplicate"
    assert len(calls) == 1 and calls[0].source_agent_id == agent["id"] and calls[0].new_agent_id == copy["id"]


async def test_delete_is_soft_and_versions_stay_readable(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    version_id = agent["draft_version"]["id"]
    assert (await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)).status_code == 204
    assert (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).status_code == 404
    version = await client.get(f"/v1/agents/{agent['id']}/versions/{version_id}", headers=account.headers)
    assert (
        version.status_code == 200 and version.json()["config"]["prompt"] == agent["draft_config"]["prompt"]
    )
    assert (await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)).status_code == 404


async def test_usage_checker_blocks_delete(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)

    async def checker(ctx: hooks.UsageContext) -> list[hooks.Attachment]:
        return [
            hooks.Attachment("phone_number", "num_01", "+14155550100"),
            hooks.Attachment("whatsapp_channel", "wa_01", "Support line"),
        ]

    with hooks.registered(usage_checkers=[checker]):
        response = await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)
    assert response.status_code == 409 and response.json()["code"] == "agent_in_use"
    assert [a["kind"] for a in response.json()["attachments"]] == ["phone_number", "whatsapp_channel"]
    assert (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).status_code == 200
