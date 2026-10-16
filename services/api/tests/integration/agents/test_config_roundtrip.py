"""Every AgentConfig path survives save and reload (T091, data-model section 4)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.agent_helpers import create_ok, save
from tests.conftest import Account


def non_default(agent_type: str, upload_key: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": agent_type,
        "language": "de",
        "llm": {"provider": "openai", "model": "gpt-5.2", "temperature": 1.0},
        "prompt": "Du hilfst {{kunde}} mit Bestellung {{bestellung}}."
        if agent_type == "single_prompt"
        else "",
        "begin_message": "Hallo {{kunde}}!",
        "start_speaker": "user",
        "dynamic_variables": [
            {"name": "kunde", "default": "Kim", "description": "Customer name"},
            {"name": "bestellung", "default": None, "description": None},
        ],
        "stt": {"provider": "deepgram", "model": "nova-2"},
        "tts": {
            "provider": "cartesia",
            "model": "sonic-3",
            "voice_id": "ac197a78-cec7-4c50-93e5-93bdc1910b11",
            "speed": 1.3,
            "expressiveness": 1.5,
            "volume": 0.75,
        },
        "noise_cancellation": {"provider": "ai_coustics", "model": "standard"},
        "call_behavior": {
            "end_on_silence_s": 120,
            "max_duration_s": 1800,
            "ring_duration_ms": 1500,
            "interruption_sensitivity": 0.35,
            "responsiveness": 0.6,
        },
        "advanced": {
            "webhook_url": "https://hooks.example.com/de",
            "webhook_timeout_ms": 12000,
            "voicemail_detection": {
                "enabled": True,
                "action": "leave_message",
                "message": "Bitte zurueckrufen.",
            },
            "dtmf": {"enabled": True, "timeout_ms": 4500, "termination_key": "*", "digits": 6},
            "background_audio": {
                "enabled": True,
                "source": {"kind": "upload", "key": upload_key},
                "volume": 1.25,
            },
            "analysis_model": {"provider": "azure_openai", "model": "gpt-5-mini"},
            "pronunciation": [{"word": "GmbH", "replacement": "Gesellschaft"}],
            "recording": "off",
        },
        "tool_ids": ["tool_01", "tool_02"],
        "kb_ids": ["kb_01"],
        "flow": {"flow_id": "flw_x", "graph": {"nodes": []}} if agent_type == "flow" else None,
        "evals": {"enabled": ["intent"]},
    }


@pytest.mark.parametrize("agent_type", ["single_prompt", "flow"])
async def test_every_path_persists(client: httpx.AsyncClient, account: Account, agent_type: str) -> None:
    upload = await client.post(
        "/v1/voices/ambient-audio",
        files={"file": ("bg.wav", b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32, "audio/wav")},
        headers=account.headers,
    )
    assert upload.status_code == 201, upload.text
    agent = await create_ok(
        client,
        account,
        agent_type=agent_type,
        config={"prompt": "x" if agent_type == "single_prompt" else ""},
    )
    target = non_default(agent_type, upload.json()["key"])
    response = await save(client, account, agent, target)
    assert response.status_code == 200, response.text
    assert response.json()["created"] is True
    reloaded = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert reloaded["draft_config"] == target
    version_id = response.json()["version"]["id"]
    version = (
        await client.get(f"/v1/agents/{agent['id']}/versions/{version_id}", headers=account.headers)
    ).json()
    assert version["config"] == target
