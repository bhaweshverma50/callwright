"""The evaluation spend read from the ledger: what was charged for a set of calls' runs."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI

from app.billing import service as billing
from app.evals.views import billed_for_calls
from tests.conftest import Account
from tests.quality_support import seed_agent, seed_call, seed_run
from tests.runtime_support import owner_sql


async def test_sums_ledger_charges_of_the_calls_runs(app: FastAPI, account: Account) -> None:
    ws = account.workspace_id
    agent = seed_agent(ws)
    charged, free, other = (seed_call(ws, agent) for _ in range(3))
    run_a = seed_run(ws, charged, agent[0], "intent_fulfillment", "pass")
    seed_run(ws, free, agent[0], "intent_fulfillment", "pass")
    run_c = seed_run(ws, other, agent[0], "intent_fulfillment", "pass")
    async with app.state.db.transaction(workspace_id=ws) as session:
        for run_id, amount in ((run_a, "0.012500"), (run_c, "0.500000")):
            charge = await billing.charge_feature(
                session,
                workspace_id=ws,
                feature_key="eval.intent_fulfillment",
                quantity=Decimal(1),
                unit="tokens",
                raw_cost_usd=Decimal(amount),
                billable_cost_usd=Decimal(amount),
                idempotency_key=f"test-billed:{run_id}",
            )
            assert charge.txn is not None
            owner_sql("update evaluator_runs set charge_txn_id = %s where id = %s", (charge.txn.id, run_id))
    async with app.state.db.transaction(workspace_id=ws) as session:
        assert await billed_for_calls(session, [charged, free]) == Decimal("0.0125")
        assert await billed_for_calls(session, [charged, free, other]) == Decimal("0.5125")
        assert await billed_for_calls(session, []) == Decimal(0)
