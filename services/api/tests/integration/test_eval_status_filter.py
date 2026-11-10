"""The calls list filter by evaluation status agrees with each row's badge (006 FR-032): both
read a call's current runs, the newest unsuperseded run per evaluator, for all five statuses."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.quality_support import seed_agent, seed_call, seed_run


async def listed(client: httpx.AsyncClient, account: Account, status: str) -> dict[str, str]:
    body = (await client.get("/v1/calls", params={"eval_status": status}, headers=account.headers)).json()
    return {c["call_id"]: c["quality"]["eval_status"] for c in body["items"]}


async def test_filter_matches_badge(client: httpx.AsyncClient, account: Account) -> None:
    ws = account.workspace_id
    agent = seed_agent(ws)
    # An older failing run that was never superseded, then a newer passing run: current is pass.
    rerun = seed_call(ws, agent)
    seed_run(ws, rerun, agent[0], "intent_fulfillment", "fail")
    seed_run(ws, rerun, agent[0], "intent_fulfillment", "pass")
    failing = seed_call(ws, agent)
    seed_run(ws, failing, agent[0], "intent_fulfillment", "fail")
    skipped = seed_call(ws, agent)
    seed_run(ws, skipped, agent[0], "intent_fulfillment", "pass", status="skipped")
    unevaluated = seed_call(ws, agent)
    running = seed_call(ws, agent)
    seed_run(ws, running, agent[0], "intent_fulfillment", "pass", status="running")
    errored = seed_call(ws, agent)
    seed_run(ws, errored, agent[0], "intent_fulfillment", "pass", status="error")

    passed = await listed(client, account, "passed")
    assert passed == {rerun: "passed"}
    failed = await listed(client, account, "failed")
    assert failed == {failing: "failed"}
    not_evaluated = await listed(client, account, "not_evaluated")
    assert set(not_evaluated) == {skipped, unevaluated}
    assert set(not_evaluated.values()) == {"not_evaluated"}
    assert await listed(client, account, "running") == {running: "running"}
    assert await listed(client, account, "error") == {errored: "error"}
