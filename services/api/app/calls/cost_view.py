"""Call cost view (006 T027, FR-015): 001's stored breakdown mapped to header, lines and surcharges.

Reads the lines 001 priced and stored; nothing is recomputed except the display figures derived
from them: ``avg_rate_per_min_usd = total_usd / (duration_s / 60)`` and the surcharge multiplier
rounded to two places (1.1330 shows as 1.13). A zero-cost noise cancellation line is omitted;
surcharge lines appear only for components whose surcharge is above zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

SURCHARGE_LABELS = {"llm": "Model token surcharge", "tts": "Speech character surcharge"}
_SIX = Decimal("0.000001")
_TWO = Decimal("0.01")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _num(value: Decimal) -> float:
    return float(value.quantize(_SIX, rounding=ROUND_HALF_UP))


def cost_view(stored: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``stored`` is 001's ``call_cost_json`` (or ``breakdown_json``); None when not priced."""
    if not stored:
        return None
    duration_s = int(stored.get("billed_seconds") or 0)
    total = _dec(stored.get("total_usd"))
    billed_minutes = _dec(stored.get("duration_minutes")) if duration_s else Decimal(0)
    avg_rate = total / (Decimal(duration_s) / 60) if duration_s else Decimal(0)
    lines: list[dict[str, Any]] = []
    surcharges: list[dict[str, Any]] = []
    for raw in stored.get("lines") or []:
        component = str(raw.get("component"))
        cost = _dec(raw.get("cost_usd"))
        if component == "nc" and cost == 0:
            continue
        lines.append(
            {
                "component": component,
                "provider": raw.get("provider"),
                "model": raw.get("model"),
                "rate_per_min_usd": _num(_dec(raw.get("rate_per_min_usd"))),
                "billed_minutes": _num(_dec(raw.get("billed_minutes"))),
                "cost_usd": _num(cost),
            }
        )
        surcharge = _dec(raw.get("surcharge_usd"))
        if component in SURCHARGE_LABELS and surcharge > 0:
            multiplier = _dec(raw.get("bundle_multiplier") or 1).quantize(_TWO, rounding=ROUND_HALF_UP)
            surcharges.append(
                {
                    "component": component,
                    "label": SURCHARGE_LABELS[component],
                    "surcharge_usd": _num(surcharge),
                    "multiplier": float(multiplier),
                }
            )
    return {
        "header": {
            "duration_s": duration_s,
            "billed_minutes": _num(billed_minutes),
            "avg_rate_per_min_usd": _num(avg_rate),
            "total_usd": _num(total),
        },
        "lines": lines,
        "surcharges": surcharges,
        "catalog_version": str(stored.get("catalog_version", "")),
    }
