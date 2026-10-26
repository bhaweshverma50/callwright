"""Copilot speech-to-text adapters (006 T075, research R7).

One adapter per vendor with two operations: mint a short-lived, transcription-only credential the
browser streams with, and transcribe a recorded clip (the fallback). ``FakeSttAdapter`` serves dev
and tests: it has no streaming credential and cannot transcribe audio (both ``SttNotConfigured``,
so the client offers typing), and reads a ``text/plain`` clip as its text.
"""

from __future__ import annotations

from typing import Any, Protocol


class SttUnavailable(Exception):
    """The vendor could not mint a credential or transcribe; the caller answers 503."""


class SttNotConfigured(SttUnavailable):
    """No transcription vendor is configured (no key): recording a clip would be pointless."""


class SttCommandAdapter(Protocol):
    name: str

    async def mint_stream_credential(self, ttl_s: int) -> dict[str, Any]: ...

    async def transcribe(self, audio: bytes, mime: str) -> str: ...


class FakeSttAdapter:
    name = "fake"

    async def mint_stream_credential(self, ttl_s: int) -> dict[str, Any]:
        raise SttNotConfigured("no streaming transcription configured")

    async def transcribe(self, audio: bytes, mime: str) -> str:
        if mime != "text/plain":
            raise SttNotConfigured("no transcription vendor configured")
        try:
            return audio.decode("utf-8").strip()[:1000]
        except UnicodeDecodeError:
            return ""
