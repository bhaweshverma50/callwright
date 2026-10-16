"""Ambient audio uploads (T030, research R19)."""

from __future__ import annotations

import copy
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI

from app.voices.service import sniff_audio
from tests.agent_helpers import create_ok, save
from tests.conftest import Account

URL = "/v1/voices/ambient-audio"
SAMPLES = {
    "audio/mpeg": b"ID3\x04\x00" + b"\x00" * 32,
    "audio/wav": b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 32,
    "audio/ogg": b"OggS\x00\x02" + b"\x00" * 22 + b"\x01vorbis" + b"\x00" * 16,
    "audio/opus": b"OggS\x00\x02" + b"\x00" * 22 + b"OpusHead" + b"\x00" * 16,
    "audio/flac": b"fLaC" + b"\x00" * 32,
    "audio/aac": b"\xff\xf1\x50\x80" + b"\x00" * 32,
}


def test_magic_bytes() -> None:
    for content_type, data in SAMPLES.items():
        assert sniff_audio(data) == content_type
    assert sniff_audio(b"\xff\xfb\x90\x00") == "audio/mpeg"
    assert sniff_audio(b"<html>") is None
    assert sniff_audio(b"PK\x03\x04") is None


async def test_upload_preview_and_delete_guard(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    uploaded = await client.post(
        URL,
        files={"file": ("rain.ogg", SAMPLES["audio/ogg"], "application/octet-stream")},
        headers=account.headers,
    )
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["content_type"] == "audio/ogg" and body["filename"] == "rain.ogg"
    assert body["key"].endswith(".ogg") and body["size_bytes"] == len(SAMPLES["audio/ogg"])
    preview = urlsplit(body["preview_url"])
    served = await client.get(f"{preview.path}?{preview.query}")
    assert served.status_code == 200 and served.content == SAMPLES["audio/ogg"]
    tampered = await client.get(f"{preview.path}?{preview.query.replace('sig=', 'sig=0')}")
    assert tampered.status_code == 404

    agent = await create_ok(client, account)
    config = copy.deepcopy(agent["draft_config"])
    config["advanced"]["background_audio"] = {
        "enabled": True,
        "source": {"kind": "upload", "key": body["key"]},
        "volume": 0.8,
    }
    saved = await save(client, account, agent, config)
    assert saved.status_code == 200
    refused = await client.delete(f"{URL}?key={body['key']}", headers=account.headers)
    assert refused.status_code == 409 and refused.json()["code"] == "audio_in_use"

    # Published version still uses it after the draft moves on: still refused.
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": saved.json()["version"]["id"]},
        headers=account.headers,
    )
    config["advanced"]["background_audio"] = {"enabled": False, "source": None, "volume": 0.8}
    await save(client, account, saved.json()["agent"], config)
    assert (await client.delete(f"{URL}?key={body['key']}", headers=account.headers)).status_code == 409

    await client.delete(f"/v1/agents/{agent['id']}/published-version", headers=account.headers)
    assert (await client.delete(f"{URL}?key={body['key']}", headers=account.headers)).status_code == 204
    assert body["key"] not in [
        i["key"] for i in (await client.get(URL, headers=account.headers)).json()["items"]
    ]


async def test_upload_key_of_other_workspace_refused(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    config = copy.deepcopy(agent["draft_config"])
    config["advanced"]["background_audio"] = {
        "enabled": True,
        "source": {"kind": "upload", "key": "workspaces/ws_other/ambient/x.mp3"},
        "volume": 0.8,
    }
    response = await save(client, account, agent, config)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "missing_reference"


async def test_deleted_upload_is_publish_blocker(client: httpx.AsyncClient, account: Account) -> None:
    uploaded = (
        await client.post(
            URL, files={"file": ("a.flac", SAMPLES["audio/flac"], "audio/flac")}, headers=account.headers
        )
    ).json()
    await client.delete(f"{URL}?key={uploaded['key']}", headers=account.headers)
    agent = await create_ok(
        client,
        account,
        config={
            "prompt": "x",
            "advanced": {
                "background_audio": {"enabled": True, "source": {"kind": "upload", "key": uploaded["key"]}}
            },
        },
    )
    assert [b["code"] for b in agent["publish_blockers"]] == ["missing_reference"]
