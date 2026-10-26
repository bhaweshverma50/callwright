"""Signed recording links (006 T031, FR-011, research R9).

A link is valid for at most ``RECORDING_URL_TTL_S`` (capped at 600 s). States from 003's
``calls.recording_status``: ``recording`` is still being finalised (409 ``recording_processing``);
``available`` with a key gives a link; ``available`` whose key the retention purge cleared is
410 ``recording_deleted``; anything else (``none``, ``failed``, ``not_recorded``) is 404
``not_recorded``. The attachment variant names the file after the call ID.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.storage import ObjectStore

MAX_TTL_S = 600
CONTENT_TYPES = {
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
}

# (key, ttl_s, download filename or None) -> URL
Signer = Callable[[str, int, str | None], Awaitable[str]]


class _RecordingCall(Protocol):
    id: str
    recording_status: str
    recording_key: str | None
    billable_seconds: int | None


async def recording_link(
    call: _RecordingCall,
    sign: Signer,
    *,
    ttl_s: int,
    disposition: Literal["inline", "attachment"],
    now: datetime,
) -> dict[str, Any]:
    if call.recording_status == "recording":
        raise ProblemError(
            409,
            "recording_processing",
            "Recording not ready",
            "The recording is still being finalised. Try again shortly.",
        )
    if call.recording_status != "available":
        raise ProblemError(404, "not_recorded", "No recording", "This call has no recording.")
    if not call.recording_key:
        raise ProblemError(
            410, "recording_deleted", "Recording deleted", "Recording deleted under your retention policy."
        )
    ext = PurePosixPath(call.recording_key).suffix.lstrip(".").lower() or "ogg"
    filename = f"{call.id}.{ext}"
    ttl = max(1, min(ttl_s, MAX_TTL_S))
    url = await sign(call.recording_key, ttl, filename if disposition == "attachment" else None)
    return {
        "url": url,
        "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        "content_type": CONTENT_TYPES.get(ext, "application/octet-stream"),
        "filename": filename,
        "duration_s": call.billable_seconds,
    }


def build_signer(settings: Settings, store: ObjectStore) -> Signer:
    """S3 presigned GET on the recordings bucket in ``s3`` storage mode; the dev store otherwise."""
    if settings.storage_mode != "s3":

        async def fake(key: str, ttl_s: int, download_name: str | None) -> str:
            return await store.signed_url(key, ttl_s)

        return fake

    import boto3

    access = settings.recordings_s3_access_key or settings.s3_access_key_id
    secret = settings.recordings_s3_secret_key or settings.s3_secret_access_key
    client: Any = boto3.client(
        "s3",
        endpoint_url=settings.recordings_s3_endpoint or settings.s3_endpoint_url,
        region_name=settings.recordings_s3_region,
        aws_access_key_id=access.get_secret_value() if access else None,
        aws_secret_access_key=secret.get_secret_value() if secret else None,
    )

    async def s3(key: str, ttl_s: int, download_name: str | None) -> str:
        params: dict[str, str] = {"Bucket": settings.recordings_bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        url: str = await asyncio.to_thread(
            client.generate_presigned_url, "get_object", Params=params, ExpiresIn=ttl_s
        )
        return url

    return s3
