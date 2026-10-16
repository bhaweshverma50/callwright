"""ElevenLabs voice listing (T035): live ``GET /v2/voices`` with server-side search and token
paging; gender, language and model filters apply locally to each page. Without an API key the
adapter serves the bundled premade-voice sample (fake mode)."""

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
    matches,
    normal_gender,
)

BASE_URL = "https://api.elevenlabs.io"


def normalise(raw: dict[str, Any]) -> Voice:
    labels = raw.get("labels") or {}
    verified = raw.get("verified_languages") or []
    languages = sorted({str(v["language"]) for v in verified if isinstance(v, dict) and v.get("language")})
    if not languages and labels.get("language"):
        languages = [str(labels["language"])]
    model_ids = sorted(
        {str(v["model_id"]) for v in verified if isinstance(v, dict) and v.get("model_id")}
        | {str(m) for m in raw.get("high_quality_base_model_ids") or []}
    )
    return {
        "voice_id": str(raw["voice_id"]),
        "provider": "elevenlabs",
        "name": str(raw.get("name") or raw["voice_id"]),
        "description": raw.get("description") or labels.get("description") or None,
        "gender": normal_gender(labels.get("gender")),
        "languages": languages or ["en"],
        "preview_url": raw.get("preview_url") or None,
        "model_ids": model_ids,
    }


class ElevenLabsAdapter:
    provider = "elevenlabs"

    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.client = client

    async def list_voices(self, filters: VoiceFilters, cursor: str | None, limit: int) -> VoicePage:
        if not self.api_key:
            return local_page(load_sample(self.provider), filters, cursor, limit)
        params: dict[str, Any] = {"page_size": limit, "include_total_count": "false"}
        if filters.search:
            params["search"] = filters.search
        if cursor:
            params["next_page_token"] = cursor
        try:
            client = self.client or httpx.AsyncClient(timeout=10.0)
            try:
                response = await client.get(
                    f"{BASE_URL}/v2/voices", params=params, headers={"xi-api-key": self.api_key}
                )
            finally:
                if self.client is None:
                    await client.aclose()
            response.raise_for_status()
            body = response.json()
            voices = [normalise(v) for v in body.get("voices", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise VoiceListingError(str(exc)) from exc
        local = VoiceFilters(gender=filters.gender, language=filters.language, model=filters.model)
        items = [v for v in voices if matches(v, local)]
        next_cursor = body.get("next_page_token") if body.get("has_more") else None
        return VoicePage(items, str(next_cursor) if next_cursor else None)
