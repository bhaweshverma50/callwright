"""charge_call: ledger row, stored breakdown, usage row, idempotency, version pinning (T064, US2.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.billing import service
from app.billing.models import CallCost, CreditTransaction
from app.pricing import engine
from app.usage.models import UsageEvent
from tests.conftest import Account
from tests.runtime_support import insert_call

REFERENCE = engine.Components(
    stt=engine.Selection("deepgram", "nova-3"),
    llm=engine.Selection("azure_openai", "gpt-5-mini"),
    tts=engine.Selection("elevenlabs", "eleven_flash_v2_5"),
)
METERS = {"llm_input_tokens": 102_348, "llm_output_tokens": 745, "tts_chars": 2_555}


def _usage(
    ws: str,
    call_id: str,
    *,
    started_at: datetime | None = None,
    duration_ms: int = 271_000,
    components: engine.Components = REFERENCE,
) -> service.CallUsage:
    return service.CallUsage(
        workspace_id=ws,
        call_id=call_id,
        agent_version_id=None,
        started_at=started_at or datetime.now(UTC),
        duration_ms=duration_ms,
        components=components,
        meters=METERS,
    )


async def _charge(app: FastAPI, usage: service.CallUsage) -> CallCost:
    async with app.state.db.transaction(workspace_id=usage.workspace_id) as session:
        return await service.charge_call(session, usage)


async def test_reference_call_charge(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    call_id = insert_call(account.workspace_id)
    cost = await _charge(app, _usage(account.workspace_id, call_id))
    assert cost.total_usd == Decimal("0.477")
    assert cost.catalog_version == 1
    assert cost.billed_seconds == 271
    assert [line["cost_usd"] for line in cost.lines] == ["0.039000", "0.008000", "0.204000", "0.226000"]
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        txns = list(
            (
                await session.execute(select(CreditTransaction).where(CreditTransaction.call_id == call_id))
            ).scalars()
        )
        events = list(
            (await session.execute(select(UsageEvent).where(UsageEvent.ref_id == call_id))).scalars()
        )
    assert [(t.type, t.amount_usd) for t in txns] == [("call_charge", Decimal("-0.477000"))]
    assert cost.txn_id == txns[0].id
    assert len(events) == 1
    assert events[0].feature_key == "calls" and events[0].billable_cost_usd == Decimal("0.477")
    assert events[0].raw_cost_usd == Decimal("0.249318")
    assert events[0].txn_id == txns[0].id

    detail = await client.get(f"/v1/billing/transactions/{txns[0].id}", headers=account.headers)
    body = detail.json()
    assert body["call_id"] == call_id
    assert body["cost_breakdown"]["total_usd"] == "0.477000"
    assert body["cost_breakdown"]["catalog_version"] == 1
    llm = body["cost_breakdown"]["lines"][1]
    assert (llm["billed_minutes"], llm["surcharge_usd"], llm["bundle_multiplier"]) == (
        "5.117400",
        "0.000901",
        "1.1330",
    )
    listed = (await client.get("/v1/billing/transactions?type=call_charge", headers=account.headers)).json()
    assert listed["items"][0]["cost_breakdown"]["total_usd"] == "0.477000"
    assert (await client.get("/v1/billing/balance", headers=account.headers)).json()[
        "balance_usd"
    ] == "4.523000"


async def test_second_charge_is_a_no_op(app: FastAPI, account: Account) -> None:
    call_id = insert_call(account.workspace_id)
    first = await _charge(app, _usage(account.workspace_id, call_id))
    second = await _charge(app, _usage(account.workspace_id, call_id))
    assert second.txn_id == first.txn_id
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        count = len(
            list(
                (
                    await session.execute(
                        select(CreditTransaction).where(
                            CreditTransaction.type == "call_charge",
                            CreditTransaction.workspace_id == account.workspace_id,
                        )
                    )
                ).scalars()
            )
        )
    assert count == 1


async def test_call_charge_may_take_the_balance_below_zero(app: FastAPI, account: Account) -> None:
    for _ in range(12):
        await _charge(app, _usage(account.workspace_id, insert_call(account.workspace_id)))
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        assert await service.get_balance(session, account.workspace_id) == Decimal("5") - 12 * Decimal(
            "0.477"
        )


async def test_zero_second_call_writes_usage_but_no_ledger_row(app: FastAPI, account: Account) -> None:
    call_id = insert_call(account.workspace_id)
    cost = await _charge(app, _usage(account.workspace_id, call_id, duration_ms=0))
    assert cost.total_usd == 0 and cost.txn_id is None
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        event = (await session.execute(select(UsageEvent).where(UsageEvent.ref_id == call_id))).scalar_one()
    assert event.txn_id is None and event.billable_cost_usd == 0


async def test_unpriced_component_refuses_the_charge(app: FastAPI, account: Account) -> None:
    components = engine.Components(REFERENCE.stt, REFERENCE.llm, engine.Selection("not_a_vendor"))
    with pytest.raises(service.PricingUnavailable) as info:
        await _charge(
            app, _usage(account.workspace_id, insert_call(account.workspace_id), components=components)
        )
    assert info.value.components == ("tts",)


async def test_older_call_keeps_its_catalog_version(
    app: FastAPI, account: Account, future_catalog: int
) -> None:
    old = await _charge(app, _usage(account.workspace_id, insert_call(account.workspace_id)))
    later = await _charge(
        app,
        _usage(
            account.workspace_id,
            insert_call(account.workspace_id),
            started_at=datetime(2099, 1, 2, tzinfo=UTC),
        ),
    )
    assert old.catalog_version == 1 and old.lines[0]["rate_per_min_usd"] == "0.008500"
    assert later.catalog_version == future_catalog
    assert later.lines[0]["rate_per_min_usd"] == "0.017000"
    assert later.total_usd == Decimal("0.515")  # STT 0.0767833 rounds up to 0.077, plus 0.438
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        reread = await session.get(CallCost, old.call_id)
    assert reread is not None and reread.catalog_version == 1


async def test_call_costs_outlive_their_calls() -> None:
    """``call_costs.call_id`` referenced ``calls`` (s003_0002) until s024_0001 dropped it: erasing an
    account deletes its calls but keeps the cost rows (billing records) under the tombstone workspace."""
    from tests.runtime_support import owner_sql

    refs = owner_sql(
        "select count(*) from pg_constraint where conrelid = 'call_costs'::regclass "
        "and confrelid = 'calls'::regclass"
    )
    assert refs == [(0,)]
