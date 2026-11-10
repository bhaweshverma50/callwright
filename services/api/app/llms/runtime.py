"""The one model runtime for the API's post-call and testing work (007 evaluators and analysis,
008 simulations and test runs, 009 issues): the ``llms`` client and the embedder.

``install(settings)`` runs from the evals feature's ``install`` (API and jobs worker alike); tests
swap parts with ``install(..., llm=FakeLlm(...))``. Offline (no vendor key) the
fake adapter answers with the replies each feature registered for its ``purpose``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.llms.adapters.base import ChatMessage, Completion, LlmAdapter
from app.llms.embeddings import EmbeddingAdapter, build_embedder


class CompletionClient(Protocol):
    def adapter_for(self, provider: str) -> LlmAdapter: ...

    async def complete(
        self,
        ref: Any,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        timeout_s: float = 60.0,
        json_mode: bool = False,
        purpose: str | None = None,
    ) -> Completion: ...


@dataclass
class ModelRuntime:
    settings: Settings
    llm: CompletionClient
    embedder: EmbeddingAdapter


_runtime: ModelRuntime | None = None


def install(
    settings: Settings | None = None,
    *,
    llm: CompletionClient | None = None,
    embedder: EmbeddingAdapter | None = None,
) -> ModelRuntime:
    global _runtime
    from app.llms.client import LlmClient

    settings = settings or get_settings()
    _runtime = ModelRuntime(
        settings=settings,
        llm=llm or LlmClient(settings),
        embedder=embedder if embedder is not None else build_embedder(settings),
    )
    return _runtime


def runtime() -> ModelRuntime:
    return _runtime or install()
