"""Shared types for voice listing adapters (T035, research R7).

Every adapter returns voices in one normalised shape (contracts/voices.yaml ``Voice``):
``{voice_id, provider, name, description, gender, languages[], preview_url, model_ids[]}``.
Search and filters run at the vendor when it supports them, otherwise locally over the loaded
list (``local_page``). Cursors are opaque strings.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

Voice = dict[str, Any]
SAMPLES = Path(__file__).with_name("samples")
GENDERS = {"female": "female", "feminine": "female", "male": "male", "masculine": "male"}


def normal_gender(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return GENDERS.get(value.lower(), "neutral")


@dataclass(frozen=True)
class VoiceFilters:
    search: str | None = None
    gender: str | None = None
    language: str | None = None
    model: str | None = None

    def key(self) -> str:
        return json.dumps([self.search or "", self.gender or "", self.language or "", self.model or ""])


@dataclass(frozen=True)
class VoicePage:
    items: list[Voice]
    next_cursor: str | None

    def json(self) -> dict[str, Any]:
        return {"items": self.items, "next_cursor": self.next_cursor}


class VoiceListingError(Exception):
    """The vendor listing failed (network, auth, unexpected shape)."""


class VoiceAdapter(Protocol):
    provider: str

    async def list_voices(self, filters: VoiceFilters, cursor: str | None, limit: int) -> VoicePage: ...


def _language_matches(voice_languages: Iterable[str], wanted: str) -> bool:
    base = wanted.split("-")[0].lower()
    for code in voice_languages:
        lowered = code.lower()
        if lowered == wanted.lower() or lowered.split("-")[0] == base:
            return True
    return False


def matches(voice: Voice, filters: VoiceFilters) -> bool:
    if filters.search:
        needle = filters.search.strip().casefold()
        haystack = f"{voice.get('name') or ''} {voice.get('description') or ''}".casefold()
        if needle not in haystack:
            return False
    if filters.gender and voice.get("gender") != filters.gender:
        return False
    if filters.language and not _language_matches(voice.get("languages") or [], filters.language):
        return False
    model_ids = voice.get("model_ids") or []
    return not (filters.model and model_ids and filters.model not in model_ids)


def encode_offset(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        text = base64.urlsafe_b64decode(padded.encode()).decode()
        return max(0, int(text.removeprefix("o:")))
    except (ValueError, UnicodeDecodeError):
        return 0


def local_page(voices: list[Voice], filters: VoiceFilters, cursor: str | None, limit: int) -> VoicePage:
    """Search, filter and page a fully loaded list."""
    found = [v for v in voices if matches(v, filters)]
    start = decode_offset(cursor)
    page = found[start : start + limit]
    more = start + limit < len(found)
    return VoicePage(page, encode_offset(start + limit) if more else None)


def load_sample(provider: str) -> list[Voice]:
    path = SAMPLES / f"{provider}.json"
    with path.open(encoding="utf-8") as fh:
        voices: list[Voice] = json.load(fh)["voices"]
    return voices
