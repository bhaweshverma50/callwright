"""Agents list rows show what calls run: the published version, speech recognition, flow overrides."""

from __future__ import annotations

import copy
from typing import Any

import httpx

from tests.agent_helpers import blank_config, create_ok, save
from tests.conftest import Account
from tests.flow_helpers import basic, create_flow
from tests.flow_helpers import save as save_flow


async def listed(client: httpx.AsyncClient, account: Account, agent_id: str) -> dict[str, Any]:
    page = (await client.get(f"/v1/agents?search={agent_id}", headers=account.headers)).json()
    item: dict[str, Any] = page["items"][0]
    return item


async def test_published_version_wins_over_the_draft(client: httpx.AsyncClient, account: Account) -> None:
    config = blank_config(llm={"provider": "openai", "model": "gpt-5-mini", "temperature": 1.0})
    agent = await create_ok(client, account, name="Desk", config=config)
    assert (await listed(client, account, agent["id"]))["llm_model"] == "openai/gpt-5-mini"
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": agent["draft_version"]["id"]},
        headers=account.headers,
    )
    draft = copy.deepcopy(config)
    draft["llm"]["model"] = "gpt-5.1"
    draft["stt"] = {"provider": "deepgram", "model": "nova-2"}
    assert (await save(client, account, agent, draft)).status_code == 200
    row = await listed(client, account, agent["id"])
    assert row["llm_model"] == "openai/gpt-5-mini"
    assert row["stt_label"] != "Deepgram Nova 2"
    assert row["stt_label"].startswith("Deepgram")
    assert row["llm_extra_models"] == [] and row["voice_extra_labels"] == []


async def test_flow_agent_lists_models_voices_and_speech_used_by_nodes(
    client: httpx.AsyncClient, account: Account
) -> None:
    created = await create_flow(client, account)
    flow = created["flow"]
    g = basic()
    g["nodes"][1]["config"]["overrides"] = {
        "llm": {"provider": "openai", "model": "gpt-5.2"},
        "stt": {"provider": "assemblyai", "model": "universal-streaming"},
    }
    assert (await save_flow(client, account, flow, g)).status_code == 200
    row = await listed(client, account, created["agent_id"])
    assert row["llm_extra_models"] == ["openai/gpt-5.2"]
    assert len(row["stt_extra_labels"]) == 1 and row["stt_extra_labels"][0].startswith("AssemblyAI")
    assert row["stt_label"]
