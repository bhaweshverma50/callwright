"""Feature charges of detection and drafting (009 T012; spec FR-025, research R9).

``issues.detect`` is charged once per detection run (embeddings and naming tokens), keyed
``issues.detect:<run id>``; ``issues.draft_fix`` once per AI draft, keyed
``issues.draft_fix:<issue id>:<revision>``. Validation is billed through the simulation (008)
and evaluation (007) charges of its two batches. A retried charge with the same key is a no-op
(``billing.charge_feature``); a zero amount records usage without a ledger row.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.llms.client import billable_cost, token_cost

DETECT = "issues.detect"
DRAFT_FIX = "issues.draft_fix"
SIX = Decimal("0.000001")


def detect_key(run_id: str) -> str:
    return f"{DETECT}:{run_id}"


def draft_key(issue_id: str, revision: int) -> str:
    return f"{DRAFT_FIX}:{issue_id}:{revision}"


def raw_cost(
    model: str, input_tokens: int, output_tokens: int, *, embed_raw: Decimal = Decimal(0)
) -> Decimal:
    raw = embed_raw
    if input_tokens or output_tokens:
        raw += token_cost(model.partition("/")[2] or model, input_tokens, output_tokens)
    return raw


async def charge(
    session: AsyncSession,
    *,
    workspace_id: str,
    feature_key: str,
    key: str,
    raw: Decimal,
    tokens: int,
    ref_type: str,
    ref_id: str,
) -> Decimal:
    """Charge once per ``key``; returns the billed amount (raises ``insufficient_credit``)."""
    billable = billable_cost(raw) if raw > 0 else Decimal(0)
    result = await billing.charge_feature(
        session,
        workspace_id=workspace_id,
        feature_key=feature_key,
        quantity=Decimal(max(0, tokens)),
        unit="tokens",
        raw_cost_usd=raw.quantize(SIX),
        billable_cost_usd=billable,
        idempotency_key=key,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    return Decimal(result.usage_event.billable_cost_usd)
