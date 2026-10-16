"""Cartesia voice listing (T035): the vendor has no search, so the full list is loaded (cached by
the service for an hour) and searched and filtered locally by name, description, gender and
language. Without an API key the adapter serves its bundled sample (fake mode)."""

from __future__ import annotations

from typing import Any

import httpx

from app.voices.adapters.base import (
    Voice,
    VoiceFilters,
    VoiceListingError,
    VoicePage,
    load_sample,
    local_page,
    normal_gender,
)

BASE_URL = "https://api.cartesia.ai"
API_VERSION = "2025-04-16"
PAGE_LIMIT = 100
MAX_PAGES = 50


def normalise(raw: dict[str, Any]) -> Voice:
    language = raw.get("language")
    return {
        "voice_id": str(raw["id"]),
        "provider": "cartesia",
        "name": str(raw.get("name") or raw["id"]),
        "description": raw.get("description") or None,
        "gender": normal_gender(raw.get("gender")),
        "languages": [str(language)] if language else [],
        "preview_url": None,
        "model_ids": [],
    }


class CartesiaAdapter:
    provider = "cartesia"
    full_list = True

    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.client = client

    async def load_all(self) -> list[Voice]:
        if not self.api_key:
            return load_sample(self.provider)
        voices: list[Voice] = []
        after: str | None = None
        client = self.client or httpx.AsyncClient(timeout=15.0)
        try:
            for _ in range(MAX_PAGES):
                params: dict[str, Any] = {"limit": PAGE_LIMIT}
                if after:
                    params["starting_after"] = after
                response = await client.get(
                    f"{BASE_URL}/voices",
                    params=params,
                    headers={"X-API-Key": self.api_key, "Cartesia-Version": API_VERSION},
                )
                response.raise_for_status()
                body = response.json()
                voices.extend(normalise(v) for v in body.get("data", []))
                after = body.get("next_page") if body.get("has_more") else None
                if not after:
                    break
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise VoiceListingError(str(exc)) from exc
        finally:
            if self.client is None:
                await client.aclose()
        return voices

    async def list_voices(
        self, filters: VoiceFilters, cursor: str | None, limit: int, voices: list[Voice] | None = None
    ) -> VoicePage:
        return local_page(voices if voices is not None else await self.load_all(), filters, cursor, limit)
