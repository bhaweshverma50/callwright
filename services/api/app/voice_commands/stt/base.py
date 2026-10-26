"""Copilot speech-to-text adapters (006 T075, research R7).

One adapter per vendor with two operations: mint a short-lived, transcription-only credential the
browser streams with, and transcribe a recorded clip (the fallback). ``FakeSttAdapter`` serves dev
and tests: it has no streaming credential (503, so the client falls back) and reads a clip whose
bytes are UTF-8 text as that text.
"""

from __future__ import annotations

from typing import Any, Protocol


class SttUnavailable(Exception):
    """The vendor could not mint a credential or transcribe; the caller answers 503."""


class SttCommandAdapter(Protocol):
    name: str

    async def mint_stream_credential(self, ttl_s: int) -> dict[str, Any]: ...

    async def transcribe(self, audio: bytes, mime: str) -> str: ...


class FakeSttAdapter:
    name = "fake"

    async def mint_stream_credential(self, ttl_s: int) -> dict[str, Any]:
        raise SttUnavailable("no streaming transcription configured")

    async def transcribe(self, audio: bytes, mime: str) -> str:
        try:
            return audio.decode("utf-8").strip()[:1000]
        except UnicodeDecodeError:
            return ""
