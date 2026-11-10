"""Agents on vendors this deployment cannot run: warning, Needs attention, publish blocked."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from tests.agent_helpers import blank_config, create_ok, save
from tests.conftest import Account

NOT_SET_UP = "Sarvam AI speech recognition is not set up on this platform."


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | None], None]:
    def set_keys(keys: str | None) -> None:
        settings = get_settings().model_copy(
            update={"voice_vendor_keys": keys, "anthropic_api_key": SecretStr("k")}
        )
        monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
        monkeypatch.setattr("app.agents.vendors.get_settings", lambda: settings)

    return set_keys


async def sarvam_agent(client: httpx.AsyncClient, account: Account) -> dict:  # type: ignore[type-arg]
    config = blank_config(language="hi", stt={"provider": "sarvam", "model": "saaras:v3"})
    return await create_ok(client, account, name="Hindi desk", config=config)


async def test_warning_attention_and_blocked_publish(
    client: httpx.AsyncClient, account: Account, gate: Callable[[str | None], None]
) -> None:
    gate("deepgram,openai,elevenlabs")
    agent = await sarvam_agent(client, account)
    plain = await create_ok(client, account, name="English desk")
    assert {"pointer": "/stt/provider", "code": "vendor_unavailable", "message": NOT_SET_UP} in agent[
        "warnings"
    ]
    # Saving stays allowed; the list flags the agent and counts it under attention.
    page = (await client.get("/v1/agents?status=attention", headers=account.headers)).json()
    assert [a["id"] for a in page["items"]] == [agent["id"]]
    assert page["items"][0]["vendor_warnings"] == [NOT_SET_UP]
    assert page["items"][0]["has_publish_blockers"] is False
    assert page["counts"]["attention"] == 1 and plain["id"] != agent["id"]
    # Publishing is blocked with the same message.
    blocked = await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": agent["draft_version"]["id"]},
        headers=account.headers,
    )
    assert blocked.status_code == 422, blocked.text
    assert NOT_SET_UP in blocked.text
    # Picking a runnable provider clears it.
    fixed = blank_config()
    saved = await save(client, account, agent, fixed)
    assert saved.status_code == 200, saved.text
    assert not saved.json()["warnings"]
    page = (await client.get("/v1/agents?status=attention", headers=account.headers)).json()
    assert page["items"] == []


async def test_nothing_is_flagged_when_gating_is_off(
    client: httpx.AsyncClient, account: Account, gate: Callable[[str | None], None]
) -> None:
    gate(None)
    agent = await sarvam_agent(client, account)
    assert not agent["warnings"]
    page = (await client.get("/v1/agents", headers=account.headers)).json()
    assert page["counts"]["attention"] == 0 and page["items"][0]["vendor_warnings"] == []
