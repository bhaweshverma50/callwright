"""Feature charges for test runs and simulations (008 T010; research R10, FR-030).

One charge per run and feature through ``billing.charge_feature()``, keyed ``feature:<run id>``
(``feature:<run id>:<part>`` for the extras: persona extraction and tool stand-ins), so a
retried charge is a no-op. Usage arrives as tokens per role,
``{"agent": {"model": "provider/model", "input_tokens": n, "output_tokens": n}, ...}``, and is
priced at the vendor list price of each role's model (``llms.client.token_cost``) with the
feature markup (``billable_cost``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.llms.client import billable_cost, token_cost

FEATURE_KEYS = frozenset(
    {
        "testing.run",
        "testing.generate",
        "simulation.replay",
        "simulation.persona",
        "simulation.persona_extraction",
        "simulation.tool_synth",
    }
)
SIX = Decimal("0.000001")


@dataclass(frozen=True)
class RunCharge:
    billable_usd: Decimal
    raw_usd: Decimal
    created: bool


def charge_key(run_id: str, part: str | None = None) -> str:
    return f"feature:{run_id}" if part is None else f"feature:{run_id}:{part}"


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def usage_cost(usage: Mapping[str, Any], roles: Iterable[str] | None = None) -> tuple[Decimal, int]:
    """(raw cost, total tokens) of ``usage``, optionally limited to ``roles``."""
    wanted = set(roles) if roles is not None else None
    raw = Decimal(0)
    tokens = 0
    for role, entry in usage.items():
        if (wanted is not None and role not in wanted) or not isinstance(entry, Mapping):
            continue
        if entry.get("offline"):
            continue  # the runner's offline fallback answered: no vendor tokens were used
        model = str(entry.get("model") or "")
        model = model.partition("/")[2] or model
        inp, out = _int(entry.get("input_tokens")), _int(entry.get("output_tokens"))
        if inp or out:
            raw += token_cost(model or "gpt-5-mini", inp, out)
            tokens += inp + out
    return raw, tokens


def merge_usage(*parts: Mapping[str, Any]) -> dict[str, Any]:
    """Sum token counts per role (the model of the first entry per role is kept)."""
    out: dict[str, dict[str, Any]] = {}
    for part in parts:
        for role, entry in (part or {}).items():
            if not isinstance(entry, Mapping):
                continue
            current = out.setdefault(
                role, {"model": entry.get("model"), "input_tokens": 0, "output_tokens": 0}
            )
            current["model"] = current.get("model") or entry.get("model")
            current["input_tokens"] += _int(entry.get("input_tokens"))
            current["output_tokens"] += _int(entry.get("output_tokens"))
    return out


async def charge_run(
    session: AsyncSession,
    *,
    workspace_id: str,
    run_id: str,
    feature_key: str,
    usage: Mapping[str, Any],
    roles: Iterable[str] | None = None,
    part: str | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> RunCharge:
    """Charge ``usage`` once for ``run_id`` (raises ``insufficient_credit`` at or below zero)."""
    if feature_key not in FEATURE_KEYS:
        raise ValueError(f"not a testing or simulation feature: {feature_key!r}")
    raw, tokens = usage_cost(usage, roles)
    billable = billable_cost(raw) if raw > 0 else Decimal(0)
    charge = await billing.charge_feature(
        session,
        workspace_id=workspace_id,
        feature_key=feature_key,
        quantity=Decimal(tokens),
        unit="tokens",
        raw_cost_usd=raw.quantize(SIX),
        billable_cost_usd=billable,
        idempotency_key=charge_key(run_id, part),
        ref_type=ref_type,
        ref_id=ref_id,
    )
    return RunCharge(
        billable_usd=Decimal(charge.usage_event.billable_cost_usd),
        raw_usd=Decimal(charge.usage_event.raw_cost_usd),
        created=charge.created,
    )
