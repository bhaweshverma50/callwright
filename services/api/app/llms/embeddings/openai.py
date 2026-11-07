"""OpenAI embeddings (``text-embedding-3-small``, 1536 dimensions)."""

from __future__ import annotations

from typing import Any

import httpx

from app.llms.embeddings.base import DIMENSIONS, EmbeddingUnavailable

MODEL = "text-embedding-3-small"
BATCH = 128


def parse_vectors(body: dict[str, Any], expected: int) -> list[list[float]]:
    rows = sorted(body.get("data") or [], key=lambda r: int(r.get("index", 0)))
    vectors = [[float(x) for x in row["embedding"]] for row in rows]
    if len(vectors) != expected:
        raise EmbeddingUnavailable(f"expected {expected} vectors, got {len(vectors)}")
    return vectors


class OpenAIEmbeddings:
    provider = "openai"
    model = MODEL
    dimensions = DIMENSIONS
    similarity_threshold = 0.30

    def __init__(
        self, api_key: str, *, base_url: str = "https://api.openai.com/v1", timeout_s: float = 10.0
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._http = httpx.AsyncClient(timeout=timeout_s, headers={"Authorization": f"Bearer {api_key}"})

    async def _post(self, url: str, body: dict[str, Any], expected: int) -> list[list[float]]:
        try:
            response = await self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(type(exc).__name__) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise EmbeddingUnavailable(f"HTTP {response.status_code}")
        response.raise_for_status()
        return parse_vectors(response.json(), expected)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            out += await self._post(self._url, {"model": self.model, "input": batch}, len(batch))
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
