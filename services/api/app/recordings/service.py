"""Signed recording links (006 T031, FR-011, research R9).

A link is valid for at most ``RECORDING_URL_TTL_S`` (capped at 600 s). States from 003's
``calls.recording_status``: ``recording`` is still being finalised (409 ``recording_processing``);
``available`` with a key gives a link; ``available`` whose key the retention purge cleared is
410 ``recording_deleted``; anything else (``none``, ``failed``, ``not_recorded``) is 404
``not_recorded``. The attachment variant names the file after the call ID.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from app.core.errors import ProblemError
from app.core.storage import ObjectSigner

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


class _RecordingCall(Protocol):
    id: str
    recording_status: str
    recording_key: str | None
    billable_seconds: int | None


def recording_link(
    call: _RecordingCall,
    signer: ObjectSigner,
    bucket: str,
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
    url = signer.presign_get(
        bucket, call.recording_key, ttl, filename if disposition == "attachment" else None
    )
    return {
        "url": url,
        "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        "content_type": CONTENT_TYPES.get(ext, "application/octet-stream"),
        "filename": filename,
        "duration_s": call.billable_seconds,
    }
