"""Fish Audio voice listing (T035): the vendor's public library is a community ranking that does
not suit business agents, so only the platform's curated allow-list from ``voices/catalog.yaml``
is offered (FR-045), searched and filtered locally. No vendor call is made."""

from __future__ import annotations

from app.voices.adapters.base import Voice, VoiceFilters, VoicePage, local_page
from app.voices.catalog import TtsProvider


def curated_voices(provider: TtsProvider) -> list[Voice]:
    return [
        {
            "voice_id": v.voice_id,
            "provider": provider.provider,
            "name": v.name,
            "description": v.description,
            "gender": v.gender,
            "languages": list(v.languages),
            "preview_url": v.preview_url,
            "model_ids": [],
        }
        for v in provider.curated_voices
    ]


class FishAudioAdapter:
    provider = "fishaudio"

    def __init__(self, catalog_entry: TtsProvider) -> None:
        self.entry = catalog_entry

    async def list_voices(self, filters: VoiceFilters, cursor: str | None, limit: int) -> VoicePage:
        return local_page(curated_voices(self.entry), filters, cursor, limit)
