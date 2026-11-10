"""Language model catalog: capability YAML joined with the 001 pricing catalog (T017, R6, R8).

The YAML lists each model once with the providers that offer it, so a model has one canonical id
across providers (FR-039). Prices are never stored here: ``catalog_json`` attaches the current
per-minute rate from ``pricing`` or ``null`` (price unavailable). Withdrawn models stay
resolvable for existing configs but are hidden from pickers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.vendors import provider_available
from app.pricing import engine

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")


@dataclass(frozen=True)
class TemperatureRule:
    min: float | None = None
    max: float | None = None
    step: float | None = None
    default: float | None = None
    fixed: float | None = None
    reason: str | None = None

    @property
    def is_fixed(self) -> bool:
        return self.fixed is not None

    @property
    def default_value(self) -> float:
        if self.fixed is not None:
            return self.fixed
        assert self.default is not None
        return self.default

    def json(self) -> dict[str, Any]:
        if self.fixed is not None:
            return {"fixed": self.fixed, "reason": self.reason or ""}
        return {"min": self.min, "max": self.max, "step": self.step, "default": self.default}


@dataclass(frozen=True)
class LlmModel:
    id: str
    label: str
    family: str | None
    providers: tuple[str, ...]
    temperature: TemperatureRule
    supports_tools: bool
    context_window: int | None
    withdrawn: bool = False


@dataclass(frozen=True)
class TokenPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal


@dataclass(frozen=True)
class LlmCatalog:
    default_provider: str
    default_model: str
    providers: tuple[tuple[str, str], ...]
    models: tuple[LlmModel, ...]
    token_prices: Mapping[str, TokenPrice]
    feature_markup: Decimal

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(pid for pid, _ in self.providers)

    def has_provider(self, provider: str) -> bool:
        return provider in self.provider_ids()

    def model(self, provider: str, model_id: str) -> LlmModel | None:
        """The model when ``provider`` offers it (withdrawn models included)."""
        for model in self.models:
            if model.id == model_id and provider in model.providers:
                return model
        return None

    def models_for(self, provider: str, *, include_withdrawn: bool = False) -> list[LlmModel]:
        return [m for m in self.models if provider in m.providers and (include_withdrawn or not m.withdrawn)]


def _rule(raw: Mapping[str, Any]) -> TemperatureRule:
    if "fixed" in raw:
        return TemperatureRule(fixed=float(raw["fixed"]), reason=str(raw.get("reason") or ""))
    return TemperatureRule(
        min=float(raw["min"]), max=float(raw["max"]), step=float(raw["step"]), default=float(raw["default"])
    )


def parse_catalog(data: Mapping[str, Any]) -> LlmCatalog:
    providers = tuple((str(p["id"]), str(p["label"])) for p in data["providers"])
    models = tuple(
        LlmModel(
            id=str(m["id"]),
            label=str(m["label"]),
            family=m.get("family"),
            providers=tuple(str(p) for p in m["providers"]),
            temperature=_rule(m["temperature"]),
            supports_tools=bool(m.get("supports_tools", False)),
            context_window=m.get("context_window"),
            withdrawn=bool(m.get("withdrawn", False)),
        )
        for m in data["models"]
    )
    prices = {
        str(model_id): TokenPrice(Decimal(str(p["input"])), Decimal(str(p["output"])))
        for model_id, p in (data.get("token_prices_usd_per_mtok") or {}).items()
    }
    return LlmCatalog(
        default_provider=str(data["default"]["provider"]),
        default_model=str(data["default"]["model"]),
        providers=providers,
        models=models,
        token_prices=prices,
        feature_markup=Decimal(str(data.get("feature_markup", "1"))),
    )


@lru_cache(maxsize=1)
def load_catalog() -> LlmCatalog:
    with CATALOG_PATH.open(encoding="utf-8") as fh:
        return parse_catalog(yaml.safe_load(fh))


def label_for(provider: str) -> str:
    return dict(load_catalog().providers).get(provider, provider)


def price_json(rate: engine.Rate | None) -> str | None:
    return engine.fmt6(rate.rate_per_min_usd) if rate is not None else None


def input_bundle(rate: engine.Rate | None) -> int | None:
    if rate is None:
        return None
    return next((b.per_min for b in rate.bundles if b.unit == "llm_input_tokens"), None)


def catalog_json(
    pricing: engine.Catalog | None, *, include_withdrawn: bool = False, catalog: LlmCatalog | None = None
) -> dict[str, Any]:
    """Body of ``GET /v1/llms/catalog`` (contracts/llms.yaml ``LlmCatalog``)."""
    cat = catalog or load_catalog()
    providers = []
    for pid, label in cat.providers:
        models = []
        for model in cat.models_for(pid, include_withdrawn=include_withdrawn):
            rate = pricing.lookup("llm", pid, model.id) if pricing is not None else None
            models.append(
                {
                    "id": model.id,
                    "label": model.label,
                    "family": model.family,
                    "temperature": model.temperature.json(),
                    "supports_tools": model.supports_tools,
                    "context_window": model.context_window,
                    "input_tokens_bundle_per_min": input_bundle(rate),
                    "price_per_min_usd": price_json(rate),
                    "withdrawn": model.withdrawn,
                }
            )
        providers.append({"id": pid, "label": label, "available": provider_available(pid), "models": models})
    return {"default": {"provider": cat.default_provider, "model": cat.default_model}, "providers": providers}
