"""Voice browser and background audio uploads (T035, T036, T084; research R7, R19).

* ``list_voices``: one normalised listing for every TTS provider through
  ``voices/adapters/<vendor>.py``, cached in Redis for an hour per (provider, filters, cursor).
  A vendor failure becomes ``503 catalog_unavailable`` so the editor keeps the current voice.
* Ambient uploads: magic-byte checked audio up to 10 MB, 20 per workspace, stored at
  ``workspaces/{ws}/ambient/{ulid}.{ext}``, previewed by 10-minute signed URLs, and never
  deleted while a draft or the published version references the key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.config import Settings
from app.core.errors import ProblemError, not_found
from app.core.storage import ObjectStore
from app.voices.adapters.base import VoiceFilters, VoiceListingError, VoicePage
from app.voices.adapters.cartesia import CartesiaAdapter
from app.voices.adapters.elevenlabs import ElevenLabsAdapter
from app.voices.adapters.fishaudio import FishAudioAdapter
from app.voices.catalog import load_catalog
from app.voices.models import AmbientAudioFile

tracer = trace.get_tracer("app.voices")

CACHE_TTL_S = 3600
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOADS = 20
EXTENSIONS = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/aac": "aac",
    "audio/opus": "opus",
}


def catalog_unavailable(provider: str) -> ProblemError:
    return ProblemError(
        503,
        "catalog_unavailable",
        "Voices unavailable",
        f"The {provider} voice list could not be loaded. Try again; the current voice stays selected.",
    )


def _secret(value: Any) -> str | None:
    return value.get_secret_value() if value is not None else None


async def list_voices(
    redis: Redis,
    settings: Settings,
    provider: str,
    filters: VoiceFilters,
    cursor: str | None,
    limit: int,
) -> VoicePage:
    entry = load_catalog().tts_provider(provider)
    if entry is None:
        raise ProblemError(404, "not_found", "Not found", f"No voice provider {provider!r} is offered.")
    digest = hashlib.sha1(
        f"{filters.key()}|{cursor or ''}|{limit}".encode(), usedforsecurity=False
    ).hexdigest()
    cache_key = f"voices:{provider}:{digest}"
    cached = await redis.get(cache_key)
    if cached is not None:
        body = json.loads(cached)
        return VoicePage(body["items"], body["next_cursor"])
    with tracer.start_as_current_span("voices.list_vendor") as span:
        span.set_attribute("voices.provider", provider)
        try:
            page = await _vendor_page(redis, settings, provider, filters, cursor, limit)
        except VoiceListingError as exc:
            span.record_exception(exc)
            raise catalog_unavailable(entry.label) from exc
    await redis.set(cache_key, json.dumps(page.json()), ex=CACHE_TTL_S)
    return page


async def _vendor_page(
    redis: Redis, settings: Settings, provider: str, filters: VoiceFilters, cursor: str | None, limit: int
) -> VoicePage:
    entry = load_catalog().tts_provider(provider)
    assert entry is not None
    if entry.curated or provider == "fishaudio":
        return await FishAudioAdapter(entry).list_voices(filters, cursor, limit)
    if provider == "elevenlabs":
        return await ElevenLabsAdapter(_secret(settings.elevenlabs_api_key)).list_voices(
            filters, cursor, limit
        )
    if provider == "cartesia":
        adapter = CartesiaAdapter(_secret(settings.cartesia_api_key))
        full_key = "voices:cartesia:all"
        raw = await redis.get(full_key)
        if raw is not None:
            voices = json.loads(raw)
        else:
            voices = await adapter.load_all()
            await redis.set(full_key, json.dumps(voices), ex=CACHE_TTL_S)
        return await adapter.list_voices(filters, cursor, limit, voices)
    raise VoiceListingError(f"no listing adapter for {provider}")


def sniff_audio(head: bytes) -> str | None:
    """Content type from magic bytes, or ``None`` when the data is not a supported format."""
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"OggS"):
        return "audio/opus" if b"OpusHead" in head[:128] else "audio/ogg"
    if head.startswith(b"ID3"):
        return "audio/mpeg"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF0) == 0xF0 and (head[1] & 0x06) == 0:
        return "audio/aac"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] & 0x06) != 0:
        return "audio/mpeg"
    return None


@dataclass(frozen=True)
class UploadedFile:
    key: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


def too_large() -> ProblemError:
    return ProblemError(
        413, "file_too_large", "File too large", "Background audio files can be at most 10 MB."
    )


async def upload_ambient(
    session: AsyncSession,
    store: ObjectStore,
    *,
    workspace_id: str,
    user_id: str | None,
    filename: str,
    data: bytes,
) -> AmbientAudioFile:
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_large()
    content_type = sniff_audio(data[:256])
    if content_type is None or not data:
        raise ProblemError(
            415,
            "unsupported_media_type",
            "Unsupported file",
            "Upload an MP3, WAV, OGG, FLAC, AAC or Opus audio file.",
        )
    count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(AmbientAudioFile)
                .where(AmbientAudioFile.workspace_id == workspace_id, AmbientAudioFile.deleted_at.is_(None))
            )
        ).scalar_one()
    )
    if count >= MAX_UPLOADS:
        raise ProblemError(
            409,
            "upload_limit",
            "Upload limit reached",
            f"A workspace can keep at most {MAX_UPLOADS} uploads.",
        )
    key = f"{ambient_prefix(workspace_id)}{str(ULID()).lower()}.{EXTENSIONS[content_type]}"
    await store.put(key, data, content_type)
    row = AmbientAudioFile(
        workspace_id=workspace_id,
        storage_key=key,
        filename=(filename or "audio")[:200],
        content_type=content_type,
        size_bytes=len(data),
        created_by=user_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_ambient(session: AsyncSession, workspace_id: str) -> list[AmbientAudioFile]:
    rows = await session.execute(
        select(AmbientAudioFile)
        .where(AmbientAudioFile.workspace_id == workspace_id, AmbientAudioFile.deleted_at.is_(None))
        .order_by(AmbientAudioFile.created_at.desc(), AmbientAudioFile.id.desc())
    )
    return list(rows.scalars())


def ambient_prefix(workspace_id: str) -> str:
    """Every upload of a workspace is stored under this key prefix."""
    return f"workspaces/{workspace_id}/ambient/"


async def ambient_exists(session: AsyncSession, key: str) -> bool:
    """Whether ``key`` names an upload that has not been deleted."""
    found = await session.execute(
        select(AmbientAudioFile.id).where(
            AmbientAudioFile.storage_key == key, AmbientAudioFile.deleted_at.is_(None)
        )
    )
    return found.first() is not None


AmbientUsage = Callable[[AsyncSession, str], Awaitable[bool]]
_ambient_usage: AmbientUsage | None = None


def set_ambient_usage(fn: AmbientUsage) -> None:
    """002 agents registers whether an agent draft or published version uses an upload."""
    global _ambient_usage
    _ambient_usage = fn


async def delete_ambient(session: AsyncSession, store: ObjectStore, workspace_id: str, key: str) -> None:
    row = (
        await session.execute(
            select(AmbientAudioFile)
            .where(
                AmbientAudioFile.workspace_id == workspace_id,
                AmbientAudioFile.storage_key == key,
                AmbientAudioFile.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("upload")
    if _ambient_usage is not None and await _ambient_usage(session, key):
        raise ProblemError(
            409,
            "audio_in_use",
            "Audio in use",
            "An agent draft or published version uses this sound. Choose another sound there first.",
        )
    row.deleted_at = datetime.now(UTC)
    await session.flush()
    await store.delete(key)


async def ambient_json(store: ObjectStore, row: AmbientAudioFile) -> dict[str, Any]:
    return {
        "key": row.storage_key,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "preview_url": await store.signed_url(row.storage_key),
        "created_at": row.created_at.isoformat(),
    }
