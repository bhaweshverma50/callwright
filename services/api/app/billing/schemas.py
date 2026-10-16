"""Bodies for /v1/billing (contracts/billing.yaml)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.billing.models import CallCost, CreditTransaction
from app.billing.service import call_cost_json
from app.pricing.engine import fmt6

MONEY_PATTERN = r"^-?\d+\.\d{1,6}$"
MoneyIn = Annotated[str, Field(pattern=MONEY_PATTERN)]


class BalanceOut(BaseModel):
    balance_usd: str
    as_of_seq: int


class CheckoutRequest(BaseModel):
    amount_usd: MoneyIn

    def amount(self) -> Decimal:
        return Decimal(self.amount_usd)


class CheckoutOut(BaseModel):
    checkout_url: str
    expires_at: datetime


def transaction_json(txn: CreditTransaction, cost: CallCost | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": txn.id,
        "type": txn.type,
        "amount_usd": fmt6(Decimal(txn.amount_usd)),
        "balance_after_usd": fmt6(Decimal(txn.balance_after_usd)),
        "call_id": txn.call_id,
        "feature_key": txn.feature_key,
        "description": txn.description,
        "created_at": txn.created_at.isoformat(),
    }
    if txn.type == "call_charge":
        body["cost_breakdown"] = call_cost_json(cost) if cost is not None else None
    return body
