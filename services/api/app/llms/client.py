"""API-side model gateway (T080, research R18): one entry point for model calls made by the API
(prompt assistant now; judges, analytics chat and simulators later).

``LlmClient.complete("azure_openai/gpt-5-mini", messages, ...)`` picks the vendor adapter in
``llms/adapters/``. When the reference is ``fake`` or the provider has no configured key, the
deterministic fake adapter answers, so development and tests never need vendor keys. Costs use
the vendor list prices in ``llms/catalog.yaml`` (``token_prices_usd_per_mtok``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from app.core.config import Settings
from app.llms.adapters.anthropic import AnthropicAdapter
from app.llms.adapters.azure_openai import AzureOpenAIAdapter
from app.llms.adapters.base import ChatMessage, Completion, LlmAdapter, ModelError, ModelTimeout
from app.llms.adapters.fake import FakeAdapter
from app.llms.adapters.openai import OpenAIAdapter
from app.llms.service import load_catalog

__all__ = ["ChatMessage", "Completion", "LlmClient", "ModelError", "ModelRef", "ModelTimeout", "token_cost"]

MILLION = Decimal(1_000_000)
SIX = Decimal("0.000001")
FAKE_PRICE_MODEL = "gpt-5-mini"


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str

    @classmethod
    def parse(cls, ref: str) -> ModelRef:
        if ref == "fake":
            return cls("fake", FAKE_PRICE_MODEL)
        provider, sep, model = ref.partition("/")
        if not sep or not provider or not model:
            raise ValueError(f"model reference must be provider/model, got {ref!r}")
        return cls(provider, model)


def token_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Vendor list price of one call (raw cost of a feature charge), unrounded."""
    prices = load_catalog().token_prices.get(model) or load_catalog().token_prices[FAKE_PRICE_MODEL]
    return (
        Decimal(input_tokens) * prices.input_per_mtok + Decimal(output_tokens) * prices.output_per_mtok
    ) / MILLION


def billable_cost(raw: Decimal) -> Decimal:
    """Charged amount: list price times the feature markup, rounded up to $0.000001."""
    return (raw * load_catalog().feature_markup).quantize(SIX, rounding=ROUND_CEILING)


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def adapter_for(self, provider: str) -> LlmAdapter:
        s = self.settings
        if provider == "openai" and s.openai_api_key:
            return OpenAIAdapter(s.openai_api_key.get_secret_value())
        if provider == "azure_openai" and s.azure_openai_api_key and s.azure_openai_endpoint:
            return AzureOpenAIAdapter(
                s.azure_openai_endpoint, s.azure_openai_api_key.get_secret_value(), s.azure_openai_api_version
            )
        if provider == "anthropic" and s.anthropic_api_key:
            return AnthropicAdapter(s.anthropic_api_key.get_secret_value())
        return FakeAdapter(provider)

    async def complete(
        self,
        ref: str | ModelRef,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        timeout_s: float = 60.0,
        json_mode: bool = False,
        purpose: str | None = None,
    ) -> Completion:
        model_ref = ModelRef.parse(ref) if isinstance(ref, str) else ref
        adapter = self.adapter_for(model_ref.provider)
        try:
            return await asyncio.wait_for(
                adapter.complete(
                    model_ref.model,
                    messages,
                    system=system,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                    json_mode=json_mode,
                    purpose=purpose,
                ),
                timeout=timeout_s,
            )
        except TimeoutError as exc:
            raise ModelTimeout(f"{model_ref.provider}/{model_ref.model} timed out") from exc
