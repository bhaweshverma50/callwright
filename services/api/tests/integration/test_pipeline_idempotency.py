"""Money test (003 T075, SC-006): replaying every step twice for 100 calls creates exactly one
``call_charge`` per call and one ``call_analyzed`` notification per call."""

from __future__ import annotations

import asyncio

from app.calls import pipeline
from tests.runtime_support import Runtime, agent_config, ended_call, owner_sql

CALLS = 100


async def test_replays_never_double_charge_or_notify(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    await runtime.set_balance(ws, __import__("decimal").Decimal("100"))
    config = agent_config(advanced={"webhook_url": "https://hooks.example.com/calls"})
    setups = [await ended_call(runtime, ws, config=config, seconds=4.2, turns=1) for _ in range(CALLS)]
    ids = [s.call_id for s in setups]

    async def run(call_id: str, replay: bool) -> None:
        await pipeline.run(runtime.db, ws, call_id, catalog=runtime.catalog, replay=replay)

    # First pass, then two racing replays per call (every step runs again, handlers are idempotent).
    for call_id in ids:
        await run(call_id, False)
    for call_id in ids:
        await asyncio.gather(run(call_id, True), run(call_id, True))

    charges = owner_sql(
        "select call_id, count(*) from credit_transactions where type = 'call_charge' and call_id = any(%s) "
        "group by call_id",
        (ids,),
    )
    assert len(charges) == CALLS and all(count == 1 for _, count in charges)
    costs = owner_sql("select count(*) from call_costs where call_id = any(%s)", (ids,))
    assert costs == [(CALLS,)]
    notified = owner_sql(
        "select call_id, count(*) from webhook_deliveries "
        "where event = 'call_analyzed' and call_id = any(%s) "
        "group by call_id",
        (ids,),
    )
    assert len(notified) == CALLS and all(count == 1 for _, count in notified)
    statuses = owner_sql("select distinct status, billable_seconds from calls where id = any(%s)", (ids,))
    assert statuses == [("completed", 5)]  # 4.2 s connected bills 5 s (US4.1)
    usage_rows = owner_sql(
        "select count(*) from usage_events where idempotency_key = any(%s)",
        ([f"call_charge:{i}" for i in ids],),
    )
    assert usage_rows == [(CALLS,)]
