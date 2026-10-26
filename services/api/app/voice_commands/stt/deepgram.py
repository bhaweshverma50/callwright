"""Deepgram copilot STT adapter (006 T075): a temporary listen-only token for browser streaming
(``POST /v1/auth/grant``, TTL at most 60 s) and batch transcription for the fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.voice_commands.stt.base import SttUnavailable

API = "https://api.deepgram.com/v1"
MODEL = "nova-3"


class DeepgramSttAdapter:
    name = "deepgram"

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._http = http

    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        if self._http is not None:
            return await self._http.post(url, **kwargs)
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.post(url, **kwargs)

    async def mint_stream_credential(self, ttl_s: int) -> dict[str, Any]:
        ttl = max(1, min(60, ttl_s))
        try:
            r = await self._post(
                f"{API}/auth/grant",
                headers={"Authorization": f"Token {self._key}"},
                json={"ttl_seconds": ttl},
            )
            r.raise_for_status()
            token = r.json()["access_token"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SttUnavailable("deepgram token grant failed") from exc
        return {
            "provider": "deepgram",
            "stream_url": f"wss://api.deepgram.com/v1/listen?model={MODEL}&language=en&smart_format=true&interim_results=true",
            "auth_scheme": "websocket_subprotocol_token",
            "token": token,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
            "encoding": "webm_opus",
            "sample_rate_hz": None,
            "language": "en",
        }

    async def transcribe(self, audio: bytes, mime: str) -> str:
        try:
            r = await self._post(
                f"{API}/listen?model={MODEL}&language=en&smart_format=true",
                headers={"Authorization": f"Token {self._key}", "Content-Type": mime},
                content=audio,
            )
            r.raise_for_status()
            alt = r.json()["results"]["channels"][0]["alternatives"][0]
            return str(alt.get("transcript") or "")[:1000]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise SttUnavailable("deepgram transcription failed") from exc
