"""Voice listing adapters against recorded vendor shapes (T029, research R7)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.voices.adapters.base import VoiceFilters, VoiceListingError, decode_offset, encode_offset, local_page
from app.voices.adapters.cartesia import CartesiaAdapter
from app.voices.adapters.elevenlabs import ElevenLabsAdapter
from app.voices.adapters.fishaudio import FishAudioAdapter
from app.voices.catalog import load_catalog

EL_PAGE_1 = {
    "voices": [
        {
            "voice_id": "EXAVITQu4vr4xnSDxMaL",
            "name": "Sarah",
            "description": "Mature, reassuring",
            "preview_url": "https://storage.example/sarah.mp3",
            "labels": {"gender": "female", "accent": "american"},
            "category": "premade",
            "verified_languages": [{"language": "en", "model_id": "eleven_flash_v2_5"}],
        },
        {
            "voice_id": "pNInz6obpgDQGcFmaJgB",
            "name": "Adam",
            "description": None,
            "preview_url": None,
            "labels": {"gender": "male"},
            "verified_languages": [{"language": "en", "model_id": "eleven_multilingual_v2"}],
        },
    ],
    "has_more": True,
    "next_page_token": "tok-2",
}
CARTESIA_PAGES = [
    {
        "data": [
            {
                "id": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
                "name": "Skylar",
                "description": "Friendly guide",
                "language": "en",
                "gender": "feminine",
            },
            {
                "id": "ac197a78-cec7-4c50-93e5-93bdc1910b11",
                "name": "Jennifer",
                "description": "Support",
                "language": "de",
                "gender": "feminine",
            },
        ],
        "has_more": True,
        "next_page": "ac197a78-cec7-4c50-93e5-93bdc1910b11",
    },
    {
        "data": [
            {
                "id": "79693aee-1207-4771-a01e-20c393c89e6f",
                "name": "Marco",
                "description": "Calm helper",
                "language": "it",
                "gender": "masculine",
            },
        ],
        "has_more": False,
        "next_page": None,
    },
]


def mock_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_elevenlabs_normalises_and_pages() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=EL_PAGE_1)

    async with mock_client(handler) as client:
        adapter = ElevenLabsAdapter("key", client)
        page = await adapter.list_voices(VoiceFilters(search="calm"), "tok-1", 2)
    assert seen[0].headers["xi-api-key"] == "key"
    assert seen[0].url.params["search"] == "calm" and seen[0].url.params["next_page_token"] == "tok-1"
    assert page.next_cursor == "tok-2"
    sarah = page.items[0]
    assert sarah == {
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "provider": "elevenlabs",
        "name": "Sarah",
        "description": "Mature, reassuring",
        "gender": "female",
        "languages": ["en"],
        "preview_url": "https://storage.example/sarah.mp3",
        "model_ids": ["eleven_flash_v2_5"],
    }


async def test_elevenlabs_local_filters_on_each_page() -> None:
    async with mock_client(lambda r: httpx.Response(200, json=EL_PAGE_1)) as client:
        page = await ElevenLabsAdapter("key", client).list_voices(VoiceFilters(gender="male"), None, 50)
    assert [v["name"] for v in page.items] == ["Adam"]
    async with mock_client(lambda r: httpx.Response(200, json=EL_PAGE_1)) as client:
        page = await ElevenLabsAdapter("key", client).list_voices(
            VoiceFilters(model="eleven_flash_v2_5"), None, 50
        )
    assert [v["name"] for v in page.items] == ["Sarah"]


async def test_elevenlabs_vendor_failure() -> None:
    async with mock_client(lambda r: httpx.Response(500)) as client:
        with pytest.raises(VoiceListingError):
            await ElevenLabsAdapter("key", client).list_voices(VoiceFilters(), None, 10)


async def test_elevenlabs_fake_mode_serves_sample() -> None:
    page = await ElevenLabsAdapter(None).list_voices(VoiceFilters(search="sarah"), None, 10)
    assert [v["voice_id"] for v in page.items] == ["EXAVITQu4vr4xnSDxMaL"]


async def test_cartesia_loads_all_pages_and_searches_locally() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=CARTESIA_PAGES[len(calls) - 1])

    async with mock_client(handler) as client:
        adapter = CartesiaAdapter("key", client)
        voices = await adapter.load_all()
    assert len(calls) == 2
    assert calls[0].headers["Cartesia-Version"] and calls[1].url.params["starting_after"]
    assert [v["gender"] for v in voices] == ["female", "female", "male"]
    page = await adapter.list_voices(VoiceFilters(search="support"), None, 10, voices)
    assert [v["name"] for v in page.items] == ["Jennifer"]
    page = await adapter.list_voices(VoiceFilters(language="de-DE"), None, 10, voices)
    assert [v["name"] for v in page.items] == ["Jennifer"]
    page = await adapter.list_voices(VoiceFilters(gender="male"), None, 10, voices)
    assert [v["name"] for v in page.items] == ["Marco"]


async def test_cartesia_failure() -> None:
    async with mock_client(lambda r: httpx.Response(401, json={"error": "no"})) as client:
        with pytest.raises(VoiceListingError):
            await CartesiaAdapter("key", client).load_all()


async def test_fishaudio_curated_only() -> None:
    entry = load_catalog().tts_provider("fishaudio")
    assert entry is not None
    page = await FishAudioAdapter(entry).list_voices(VoiceFilters(), None, 100)
    assert {v["voice_id"] for v in page.items} == {v.voice_id for v in entry.curated_voices}
    ja = await FishAudioAdapter(entry).list_voices(VoiceFilters(language="ja"), None, 100)
    assert [v["name"] for v in ja.items] == ["Polite Japanese"]


def test_cursor_paging() -> None:
    voices = [{"voice_id": str(i), "name": f"v{i}", "languages": []} for i in range(5)]
    first = local_page(voices, VoiceFilters(), None, 2)
    assert [v["voice_id"] for v in first.items] == ["0", "1"] and first.next_cursor
    second = local_page(voices, VoiceFilters(), first.next_cursor, 2)
    third = local_page(voices, VoiceFilters(), second.next_cursor, 2)
    assert [v["voice_id"] for v in third.items] == ["4"] and third.next_cursor is None
    assert decode_offset(encode_offset(7)) == 7 and decode_offset("garbage!") == 0
    assert json.dumps(first.json())
