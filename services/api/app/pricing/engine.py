"""The single pricing engine (research R1, R3, R4, R15). Pure: no I/O, Decimal only.

Rules:
* Duration is rounded up to the whole second; ``duration_minutes = billed_seconds / 60``.
* For a component with bundles, ``billed_minutes = max(duration_minutes, usage / per_min)`` over
  its meters. Components without bundles (stt, nc, platform) bill ``duration_minutes``.
* ``cost = ceil_to_0.001(rate x billed_minutes)`` per line; the call total is the sum of the
  rounded lines, so a breakdown always sums to the ledger amount.
* ``surcharge = rate x (billed_minutes - duration_minutes)`` is informational (already in cost).
* A zero-second call bills nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Literal

from app.core.money import SIX

CALL_COMPONENTS = ("stt", "llm", "tts", "nc", "platform")
BUNDLE_UNITS = ("llm_input_tokens", "llm_output_tokens", "tts_chars")
SURCHARGEABLE = frozenset({"llm", "tts"})

MONEY_STEP = Decimal("0.001")
FOUR = Decimal("0.0001")
SIXTY = Decimal(60)
THOUSAND = Decimal(1000)
ZERO = Decimal(0)


def ceil_money(amount: Decimal) -> Decimal:
    """Round up to the next tenth of a cent (R1)."""
    return amount.quantize(MONEY_STEP, rounding=ROUND_CEILING)


def q6(value: Decimal) -> Decimal:
    return value.quantize(SIX, rounding=ROUND_HALF_UP)


def fmt6(value: Decimal) -> str:
    """Decimal string with exactly six places, the API money format (R2)."""
    return f"{q6(value):f}"


@dataclass(frozen=True)
class Bundle:
    unit: str
    per_min: int

    def __post_init__(self) -> None:
        if self.unit not in BUNDLE_UNITS:
            raise ValueError(f"unknown bundle unit {self.unit!r}")
        if self.per_min < 1:
            raise ValueError("bundle per_min must be at least 1")


@dataclass(frozen=True)
class Rate:
    component: str
    provider: str
    model: str | None
    label: str
    rate_per_min_usd: Decimal
    bundles: tuple[Bundle, ...] = ()
    unit: Literal["minute", "k_tokens"] = "minute"


@dataclass(frozen=True)
class Catalog:
    version: int
    effective_from: datetime
    rates: tuple[Rate, ...]

    def lookup(self, component: str, provider: str, model: str | None) -> Rate | None:
        """Exact (component, provider, model) match, then the provider-level row (R3)."""
        fallback: Rate | None = None
        for rate in self.rates:
            if rate.component != component or rate.provider != provider:
                continue
            if model is not None and rate.model == model:
                return rate
            if rate.model is None:
                fallback = rate
        return fallback

    def platform(self) -> Rate | None:
        return next((r for r in self.rates if r.component == "platform"), None)

    def call_rates(self) -> tuple[Rate, ...]:
        """Per-minute rows served by the public catalog (embedding rows are internal)."""
        return tuple(r for r in self.rates if r.component in CALL_COMPONENTS)


@dataclass(frozen=True)
class Selection:
    provider: str
    model: str | None = None


@dataclass(frozen=True)
class Components:
    stt: Selection
    llm: Selection
    tts: Selection
    nc: Selection | None = None

    def selected(self) -> list[tuple[str, Selection]]:
        out = [("stt", self.stt), ("llm", self.llm), ("tts", self.tts)]
        if self.nc is not None:
            out.append(("nc", self.nc))
        return out


@dataclass(frozen=True)
class Usage:
    duration_ms: int
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    tts_chars: int = 0

    def __post_init__(self) -> None:
        for name in ("duration_ms", "llm_input_tokens", "llm_output_tokens", "tts_chars"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

    def meter(self, unit: str) -> int:
        value: int = getattr(self, unit)
        return value


@dataclass(frozen=True)
class QuoteLine:
    component: str
    provider: str
    model: str | None
    label: str | None
    status: Literal["priced", "unpriced"]
    rate_per_min_usd: Decimal | None
    bundles: tuple[Bundle, ...] = ()


@dataclass(frozen=True)
class MeterUsage:
    unit: str
    used: int
    bundle_per_min: int
    included: Decimal


@dataclass(frozen=True)
class CostLine:
    component: str
    provider: str
    model: str | None
    rate_per_min_usd: Decimal
    billed_minutes: Decimal
    cost_usd: Decimal
    surcharge_usd: Decimal
    bundle_multiplier: Decimal
    meters: tuple[MeterUsage, ...]
    raw_cost_usd: Decimal


@dataclass(frozen=True)
class CostBreakdown:
    catalog_version: int
    duration_ms: int
    billed_seconds: int
    duration_minutes: Decimal
    lines: tuple[CostLine, ...]
    total_usd: Decimal
    raw_cost_usd: Decimal
    complete: bool
    unpriced: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Quote:
    catalog_version: int
    lines: tuple[QuoteLine, ...]
    per_minute_total_usd: Decimal
    complete: bool
    call: CostBreakdown | None


def _quote_lines(components: Components, catalog: Catalog) -> list[tuple[QuoteLine, Rate | None]]:
    out: list[tuple[QuoteLine, Rate | None]] = []
    for component, sel in components.selected():
        rate = catalog.lookup(component, sel.provider, sel.model)
        out.append((_quote_line(component, sel.provider, sel.model, rate), rate))
    platform = catalog.platform()
    provider = platform.provider if platform is not None else "callwright"
    out.append((_quote_line("platform", provider, None, platform), platform))
    return out


def _quote_line(component: str, provider: str, model: str | None, rate: Rate | None) -> QuoteLine:
    if rate is None:
        return QuoteLine(component, provider, model, None, "unpriced", None)
    return QuoteLine(component, provider, model, rate.label, "priced", rate.rate_per_min_usd, rate.bundles)


def _cost_line(line: QuoteLine, rate: Rate, usage: Usage, duration_minutes: Decimal) -> CostLine:
    billed = duration_minutes
    meters: list[MeterUsage] = []
    if rate.component in SURCHARGEABLE:
        for bundle in rate.bundles:
            used = usage.meter(bundle.unit)
            meters.append(
                MeterUsage(bundle.unit, used, bundle.per_min, Decimal(bundle.per_min) * duration_minutes)
            )
            if duration_minutes > 0:
                billed = max(billed, Decimal(used) / Decimal(bundle.per_min))
    exact = rate.rate_per_min_usd * billed
    multiplier = (billed / duration_minutes) if duration_minutes > 0 else Decimal(1)
    return CostLine(
        component=line.component,
        provider=line.provider,
        model=line.model,
        rate_per_min_usd=rate.rate_per_min_usd,
        billed_minutes=billed,
        cost_usd=ceil_money(exact),
        surcharge_usd=q6(rate.rate_per_min_usd * (billed - duration_minutes)),
        bundle_multiplier=multiplier.quantize(FOUR, rounding=ROUND_HALF_UP),
        meters=tuple(meters),
        raw_cost_usd=exact,
    )


def billed_seconds(duration_ms: int) -> int:
    return -(-duration_ms // 1000)


def price(components: Components, usage: Usage | None, catalog: Catalog) -> Quote:
    """Per-minute quote for a selection, plus the full call breakdown when ``usage`` is given."""
    pairs = _quote_lines(components, catalog)
    lines = tuple(line for line, _ in pairs)
    complete = all(line.status == "priced" for line in lines)
    per_minute = sum((line.rate_per_min_usd or ZERO for line in lines), ZERO)
    call: CostBreakdown | None = None
    if usage is not None:
        seconds = billed_seconds(usage.duration_ms)
        duration_minutes = Decimal(seconds) / SIXTY
        cost_lines = [
            _cost_line(line, rate, usage, duration_minutes) for line, rate in pairs if rate is not None
        ]
        call = CostBreakdown(
            catalog_version=catalog.version,
            duration_ms=usage.duration_ms,
            billed_seconds=seconds,
            duration_minutes=duration_minutes,
            lines=tuple(cost_lines),
            total_usd=sum((c.cost_usd for c in cost_lines), ZERO),
            raw_cost_usd=sum((c.raw_cost_usd for c in cost_lines if c.component != "platform"), ZERO),
            complete=complete,
            unpriced=tuple(line.component for line in lines if line.status == "unpriced"),
        )
    return Quote(catalog.version, lines, per_minute, complete, call)


def price_embedding(rate: Rate, tokens: int) -> Decimal:
    """Embedding cost for ``tokens`` at a per-1,000-token rate, rounded up to $0.000001 (T090)."""
    if rate.unit != "k_tokens":
        raise ValueError("embedding pricing needs a k_tokens rate")
    if tokens < 0:
        raise ValueError("tokens must not be negative")
    if tokens == 0:
        return ZERO
    return (rate.rate_per_min_usd * Decimal(tokens) / THOUSAND).quantize(SIX, rounding=ROUND_CEILING)


def cost_line_json(line: CostLine) -> dict[str, Any]:
    return {
        "component": line.component,
        "provider": line.provider,
        "model": line.model,
        "rate_per_min_usd": fmt6(line.rate_per_min_usd),
        "billed_minutes": fmt6(line.billed_minutes),
        "cost_usd": fmt6(line.cost_usd),
        "surcharge_usd": fmt6(line.surcharge_usd),
        "bundle_multiplier": f"{line.bundle_multiplier:f}",
        "meters": [
            {
                "unit": m.unit,
                "used": m.used,
                "bundle_per_min": m.bundle_per_min,
                "included": fmt6(m.included),
            }
            for m in line.meters
        ],
    }


def breakdown_json(breakdown: CostBreakdown, call_id: str | None) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "catalog_version": breakdown.catalog_version,
        "duration_ms": breakdown.duration_ms,
        "billed_seconds": breakdown.billed_seconds,
        "duration_minutes": fmt6(breakdown.duration_minutes),
        "lines": [cost_line_json(line) for line in breakdown.lines],
        "total_usd": fmt6(breakdown.total_usd),
    }
