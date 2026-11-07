"""Feature charges of test runs and simulations (008 T009; research R10, FR-030, SC-005).

Written before ``simulator/charges.py``: one charge per run and feature, keyed
``feature:<run id>`` (``feature:<run id>:<part>`` for the extras), so a retried charge is a no-op.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.billing import service as billing
from app.billing.models import CreditTransaction
from app.core.errors import ProblemError
from app.core.ids import new_id
from app.pricing.features import feature_family
from app.testing.charges import FEATURE_KEYS, charge_run, usage_cost
from app.usage.models import UsageEvent
from tests.conftest import make_workspace

USAGE = {
    "agent": {"model": "azure_openai/gpt-5.1", "input_tokens": 1200, "output_tokens": 300},
    "caller": {"model": "openai/gpt-5-mini", "input_tokens": 800, "output_tokens": 100},
}


def test_feature_keys_are_registered_in_the_simulations_and_testing_families() -> None:
    assert {feature_family(k) for k in FEATURE_KEYS} == {"testing", "simulations"}


def test_usage_cost_prices_each_role_by_its_model() -> None:
    raw, tokens = usage_cost(USAGE)
    assert raw > 0 and tokens == 2400
    assert usage_cost({}) == (Decimal(0), 0)
    # Roles can be limited (the synthesizer is charged separately); each role has its own price.
    raw_agent, agent_tokens = usage_cost(USAGE, roles=("agent",))
    raw_caller, _ = usage_cost(USAGE, roles=("caller",))
    assert agent_tokens == 1500 and raw_agent + raw_caller == raw and raw_agent != raw_caller
    # Malformed entries count as zero instead of failing the run.
    assert usage_cost({"agent": {"model": "x/y", "input_tokens": "lots"}}) == (Decimal(0), 0)


async def _counts(app: FastAPI, ws: str) -> tuple[int, int]:
    async with app.state.db.transaction(workspace_id=ws) as session:
        events = (
            await session.execute(
                select(func.count()).select_from(UsageEvent).where(UsageEvent.workspace_id == ws)
            )
        ).scalar_one()
        txns = (
            await session.execute(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.workspace_id == ws, CreditTransaction.type == "feature_charge")
            )
        ).scalar_one()
    return int(events), int(txns)


async def test_retried_charge_is_a_no_op(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    run_id = new_id("srun")
    before = await _counts(app, ws)
    async with app.state.db.transaction(workspace_id=ws) as session:
        first = await charge_run(
            session,
            workspace_id=ws,
            run_id=run_id,
            feature_key="simulation.replay",
            usage=USAGE,
            ref_type="simulation_run",
            ref_id=run_id,
        )
    async with app.state.db.transaction(workspace_id=ws) as session:
        again = await charge_run(
            session,
            workspace_id=ws,
            run_id=run_id,
            feature_key="simulation.replay",
            usage=USAGE,
            ref_type="simulation_run",
            ref_id=run_id,
        )
    assert first.created and not again.created
    assert first.billable_usd == again.billable_usd > first.raw_usd > 0
    assert await _counts(app, ws) == (before[0] + 1, before[1] + 1)
    async with app.state.db.transaction(workspace_id=ws) as session:
        event = (await session.execute(select(UsageEvent).where(UsageEvent.ref_id == run_id))).scalar_one()
    assert event.feature_key == "simulation.replay" and event.unit == "tokens"
    assert event.quantity == Decimal(2400) and event.ref_id == run_id


async def test_parts_of_one_run_are_charged_separately_once_each(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    run_id = new_id("srun")
    before = await _counts(app, ws)
    for _ in range(2):
        async with app.state.db.transaction(workspace_id=ws) as session:
            await charge_run(
                session, workspace_id=ws, run_id=run_id, feature_key="simulation.persona", usage=USAGE
            )
            await charge_run(
                session,
                workspace_id=ws,
                run_id=run_id,
                feature_key="simulation.persona_extraction",
                usage={
                    "extraction": {"model": "openai/gpt-5-mini", "input_tokens": 500, "output_tokens": 80}
                },
                part="persona_extraction",
            )
    assert await _counts(app, ws) == (before[0] + 2, before[1] + 2)


async def test_zero_usage_records_usage_without_a_ledger_row(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    run_id = new_id("trn")
    before = await _counts(app, ws)
    async with app.state.db.transaction(workspace_id=ws) as session:
        charge = await charge_run(
            session, workspace_id=ws, run_id=run_id, feature_key="testing.run", usage={}
        )
    assert charge.billable_usd == Decimal(0)
    assert await _counts(app, ws) == (before[0] + 1, before[1])


async def test_unknown_feature_key_is_refused(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    async with app.state.db.transaction(workspace_id=ws) as session:
        with pytest.raises(ValueError):
            await charge_run(
                session, workspace_id=ws, run_id="srun_x", feature_key="simulation.other", usage=USAGE
            )


async def test_no_credit_refuses_a_paid_charge(app: FastAPI) -> None:
    _, ws = await make_workspace(app, trial=False)
    async with app.state.db.transaction(workspace_id=ws) as session:
        assert await billing.get_balance(session, ws) <= 0
        with pytest.raises(ProblemError) as raised:
            await charge_run(
                session, workspace_id=ws, run_id=new_id("srun"), feature_key="simulation.replay", usage=USAGE
            )
    assert raised.value.code == "insufficient_credit"
