"""Azure OpenAI embeddings: the deployment is named after the model (R13, second vendor)."""

from __future__ import annotations

import httpx

from app.knowledge.embeddings.base import DIMENSIONS, EmbeddingUnavailable
from app.knowledge.embeddings.openai import BATCH, MODEL, parse_vectors


class AzureOpenAIEmbeddings:
    provider = "azure_openai"
    model = MODEL
    dimensions = DIMENSIONS
    similarity_threshold = 0.30

    def __init__(self, endpoint: str, api_key: str, api_version: str, *, timeout_s: float = 10.0) -> None:
        self._url = f"{endpoint.rstrip('/')}/openai/deployments/{MODEL}/embeddings?api-version={api_version}"
        self._http = httpx.AsyncClient(timeout=timeout_s, headers={"api-key": api_key})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            try:
                response = await self._http.post(self._url, json={"input": batch})
            except httpx.HTTPError as exc:
                raise EmbeddingUnavailable(type(exc).__name__) from exc
            if response.status_code == 429 or response.status_code >= 500:
                raise EmbeddingUnavailable(f"HTTP {response.status_code}")
            response.raise_for_status()
            out += parse_vectors(response.json(), len(batch))
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
