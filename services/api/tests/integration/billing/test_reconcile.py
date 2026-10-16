"""Nightly reconciliation (T056, SC-003)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI

from app.billing import service
from app.billing.jobs import reconcile
from app.core.ids import new_id
from tests.conftest import make_workspace


async def test_reconcile_reports_no_mismatches(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    async with app.state.db.transaction(workspace_id=ws) as session:
        await service.post_transaction(
            session,
            workspace_id=ws,
            type="call_charge",
            amount_usd=Decimal("-0.477"),
            description="c",
            call_id=new_id("call"),
        )
    result = await reconcile(app.state.db)
    assert result.workspaces >= 1
    assert result.mismatches == []
