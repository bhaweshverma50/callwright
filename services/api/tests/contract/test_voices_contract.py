"""contracts/voices.yaml: catalog with controls, voice browser, ambient uploads (T027, T104)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.voices.adapters.base import VoiceListingError
from tests.conftest import Account
from tests.contract.conftest import check

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


async def test_voice_catalog_200_401(client: httpx.AsyncClient, account: Account) -> None:
    response = check(await client.get("/v1/voices/catalog", headers=account.headers))
    assert response.status_code == 200
    body = response.json()
    assert len(body["languages"]) == 46 and body["languages"][0]["code"] == "multi"
    assert [t["provider"] for t in body["tts"]] == ["elevenlabs", "cartesia", "fishaudio"]
    assert all(s["supports_auto"] and s["auto"]["price_per_min_usd"] for s in body["stt"])
    assert all(m["price_per_min_usd"] for s in body["stt"] for m in s["models"])
    assert all(m["price_per_min_usd"] for t in body["tts"] for m in t["models"])
    assert [n["label"] for n in body["noise_cancellation"]] == [
        "Voice isolation",
        "Standard noise removal",
        "Lightweight noise removal",
    ]
    assert {c["path"] for c in body["controls"]} >= {"/tts/speed", "/advanced/background_audio/volume"}
    assert check(await client.get("/v1/voices/catalog")).status_code == 401


async def test_voice_browser_200_401_404_503(
    client: httpx.AsyncClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    for provider in ("elevenlabs", "cartesia", "fishaudio"):
        response = check(await client.get(f"/v1/voices/{provider}/voices?limit=3", headers=account.headers))
        assert response.status_code == 200 and len(response.json()["items"]) == 3
    filtered = check(
        await client.get(
            "/v1/voices/cartesia/voices?language=de&gender=female&search=jennifer", headers=account.headers
        )
    )
    assert [v["name"] for v in filtered.json()["items"]] == ["Jennifer"]
    assert check(await client.get("/v1/voices/elevenlabs/voices")).status_code == 401
    assert check(await client.get("/v1/voices/sarvam/voices", headers=account.headers)).status_code == 404

    from app.voices import service

    async def broken(*args: object, **kwargs: object) -> None:
        raise VoiceListingError("vendor down")

    monkeypatch.setattr(service, "_vendor_page", broken)
    down = check(
        await client.get("/v1/voices/elevenlabs/voices?search=nothing-cached", headers=account.headers)
    )
    assert down.status_code == 503 and down.json()["code"] == "catalog_unavailable"


async def test_ambient_audio_contract(client: httpx.AsyncClient, account: Account, app: FastAPI) -> None:
    url = "/v1/voices/ambient-audio"
    uploaded = check(
        await client.post(url, files={"file": ("rain.wav", WAV, "audio/wav")}, headers=account.headers)
    )
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["content_type"] == "audio/wav" and body["key"].startswith(
        f"workspaces/{account.workspace_id}/ambient/"
    )
    listed = check(await client.get(url, headers=account.headers))
    assert listed.status_code == 200 and listed.json()["items"][0]["key"] == body["key"]
    assert check(await client.get(url)).status_code == 401
    assert check(await client.post(url, files={"file": ("x.wav", WAV, "audio/wav")})).status_code == 401
    unsupported = check(
        await client.post(
            url, files={"file": ("notes.txt", b"hello world", "text/plain")}, headers=account.headers
        )
    )
    assert unsupported.status_code == 415
    big = check(
        await client.post(
            url,
            files={"file": ("big.mp3", MP3 + b"\x00" * (10 * 1024 * 1024), "audio/mpeg")},
            headers=account.headers,
        )
    )
    assert big.status_code == 413
    for i in range(19):
        assert (
            await client.post(url, files={"file": (f"{i}.mp3", MP3, "audio/mpeg")}, headers=account.headers)
        ).status_code == 201
    limit = check(
        await client.post(url, files={"file": ("21.mp3", MP3, "audio/mpeg")}, headers=account.headers)
    )
    assert limit.status_code == 409 and limit.json()["code"] == "upload_limit"
    # In use by a draft: refused.
    created = await client.post(
        "/v1/agents",
        json={
            "name": "Ambient",
            "type": "single_prompt",
            "config": {
                "prompt": "x",
                "advanced": {
                    "background_audio": {"enabled": True, "source": {"kind": "upload", "key": body["key"]}}
                },
            },
        },
        headers=account.headers,
    )
    assert created.status_code == 201, created.text
    in_use = check(await client.delete(f"{url}?key={body['key']}", headers=account.headers))
    assert in_use.status_code == 409 and in_use.json()["code"] == "audio_in_use"
    keys = [i["key"] for i in (await client.get(url, headers=account.headers)).json()["items"]]
    free = next(k for k in keys if k != body["key"])
    assert check(await client.delete(f"{url}?key={free}", headers=account.headers)).status_code == 204
    assert check(await client.delete(f"{url}?key={free}", headers=account.headers)).status_code == 404
