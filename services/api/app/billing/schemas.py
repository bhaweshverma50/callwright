"""Bodies for /v1/billing (contracts/billing.yaml)."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, field_validator

from app.billing.models import CallCost, CreditTransaction
from app.billing.service import call_cost_json
from app.pricing.engine import fmt6


class BalanceOut(BaseModel):
    balance_usd: str
    as_of_seq: int


class CheckoutRequest(BaseModel):
    amount_usd: str

    @field_validator("amount_usd")
    @classmethod
    def _decimal_string(cls, value: str) -> str:
        """Accept "25" as well as "25.00"; range and cents are checked by the service (FR-008)."""
        if not re.fullmatch(r"\d{1,7}(\.\d{1,6})?", value.strip()):
            raise ValueError("Enter an amount in dollars and cents, for example 25.00.")
        return value.strip()

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
