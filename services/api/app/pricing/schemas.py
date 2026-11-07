"""Bodies for /v1/pricing and /v1/admin/pricing (contracts/pricing.yaml)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.pricing import engine
from app.pricing.service import EntryInput

ProviderStr = Annotated[str, Field(pattern=r"^[a-z0-9_]+$", max_length=64)]
MoneyIn = Annotated[str, Field(pattern=r"^-?\d+\.\d{1,6}$")]


class BundleIn(BaseModel):
    unit: Literal["llm_input_tokens", "llm_output_tokens", "tts_chars"]
    per_min: int = Field(ge=1)


class CatalogEntryIn(BaseModel):
    component: Literal["stt", "llm", "tts", "nc", "platform"]
    provider: ProviderStr
    model: str | None
    label: str = Field(min_length=1, max_length=120)
    rate_per_min_usd: MoneyIn
    bundles: list[BundleIn]

    def to_input(self) -> EntryInput:
        return EntryInput(
            component=self.component,
            provider=self.provider,
            model=self.model,
            label=self.label,
            rate_per_min_usd=Decimal(self.rate_per_min_usd),
            bundles=tuple(engine.Bundle(b.unit, b.per_min) for b in self.bundles),
        )


class PublishRequest(BaseModel):
    effective_from: datetime
    notes: str | None = Field(default=None, max_length=500)
    entries: list[CatalogEntryIn] = Field(min_length=1)


class SelectionIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str | None = None

    def to_selection(self) -> engine.Selection:
        return engine.Selection(self.provider, self.model)


class ComponentsIn(BaseModel):
    stt: SelectionIn
    llm: SelectionIn
    tts: SelectionIn
    nc: SelectionIn | None = None

    def to_components(self) -> engine.Components:
        return engine.Components(
            stt=self.stt.to_selection(),
            llm=self.llm.to_selection(),
            tts=self.tts.to_selection(),
            nc=self.nc.to_selection() if self.nc is not None else None,
        )


class UsageIn(BaseModel):
    duration_ms: int = Field(ge=0)
    llm_input_tokens: int = Field(default=0, ge=0)
    llm_output_tokens: int = Field(default=0, ge=0)
    tts_chars: int = Field(default=0, ge=0)

    def to_usage(self) -> engine.Usage:
        return engine.Usage(self.duration_ms, self.llm_input_tokens, self.llm_output_tokens, self.tts_chars)


class QuoteRequest(BaseModel):
    components: ComponentsIn
    usage: UsageIn | None = None
    at: datetime | None = None


def _bundles(bundles: tuple[engine.Bundle, ...]) -> list[dict[str, Any]]:
    return [{"unit": b.unit, "per_min": b.per_min} for b in bundles]


def entry_json(rate: engine.Rate) -> dict[str, Any]:
    return {
        "component": rate.component,
        "provider": rate.provider,
        "model": rate.model,
        "label": rate.label,
        "rate_per_min_usd": engine.fmt6(rate.rate_per_min_usd),
        "bundles": _bundles(rate.bundles),
    }


def catalog_json(catalog: engine.Catalog) -> dict[str, Any]:
    return {
        "version": catalog.version,
        "effective_from": catalog.effective_from.isoformat(),
        "entries": [entry_json(rate) for rate in catalog.call_rates()],
    }


def quote_json(quote: engine.Quote) -> dict[str, Any]:
    body: dict[str, Any] = {
        "catalog_version": quote.catalog_version,
        "lines": [
            {
                "component": line.component,
                "provider": line.provider,
                "model": line.model,
                "label": line.label,
                "status": line.status,
                "rate_per_min_usd": (
                    engine.fmt6(line.rate_per_min_usd) if line.rate_per_min_usd is not None else None
                ),
                "bundles": _bundles(line.bundles),
            }
            for line in quote.lines
        ],
        "per_minute_total_usd": engine.fmt6(quote.per_minute_total_usd),
        "complete": quote.complete,
    }
    if quote.call is not None:
        body["call"] = engine.breakdown_json(quote.call, None)
    return body
