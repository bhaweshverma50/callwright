"""Embedding adapters (T062). ``build_embedder(settings)`` picks OpenAI when ``OPENAI_API_KEY``
is set, else Azure OpenAI when configured, else the deterministic offline adapter."""

from __future__ import annotations

from app.core.config import Settings
from app.knowledge.embeddings.base import EmbeddingAdapter, EmbeddingUnavailable

__all__ = ["EmbeddingAdapter", "EmbeddingUnavailable", "build_embedder"]


def build_embedder(settings: Settings) -> EmbeddingAdapter:
    if settings.openai_api_key is not None and settings.openai_api_key.get_secret_value():
        from app.knowledge.embeddings.openai import OpenAIEmbeddings

        return OpenAIEmbeddings(settings.openai_api_key.get_secret_value())
    if settings.azure_openai_endpoint and settings.azure_openai_api_key is not None:
        from app.knowledge.embeddings.azure_openai import AzureOpenAIEmbeddings

        return AzureOpenAIEmbeddings(
            settings.azure_openai_endpoint,
            settings.azure_openai_api_key.get_secret_value(),
            settings.azure_openai_api_version,
        )
    from app.knowledge.embeddings.fake import FakeEmbeddings

    return FakeEmbeddings()
