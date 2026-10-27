"""Rerun concurrency (007 T029; FR-017, US2 scenario 6): two quick reruns give one run group and
one 409 "Checks are already running"; superseded runs stay as history."""

from __future__ import annotations

import asyncio

import httpx

from tests.conftest import Account
from tests.fakes.fake_llm import FakeLlm
from tests.quality_support import scripted_call
from tests.runtime_support import Runtime, idem, owner_sql


async def test_two_quick_reruns(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    call = await scripted_call(runtime, account.workspace_id)
    first, second = await asyncio.gather(
        client.post(f"/v1/calls/{call.call_id}/evaluations/rerun", headers={**h, **idem()}),
        client.post(f"/v1/calls/{call.call_id}/evaluations/rerun", headers={**h, **idem()}),
    )
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [202, 409], (first.text, second.text)
    refused = first if first.status_code == 409 else second
    assert refused.json()["detail"] == "Checks are already running"
    assert owner_sql(
        "select count(*) from evaluator_run_groups where call_id = %s and status = 'active'", (call.call_id,)
    ) == [(1,)]
    # Earlier results stay visible while the rerun is pending.
    body = (await client.get(f"/v1/calls/{call.call_id}/evaluations?include_history=true", headers=h)).json()
    assert body["eval_status"] == "running"
    await runtime.run_jobs("evaluate_call")
    body = (await client.get(f"/v1/calls/{call.call_id}/evaluations?include_history=true", headers=h)).json()
    assert body["eval_status"] in ("passed", "failed") and len(body["history"]) == len(body["runs"])
    assert all(r["superseded_at"] for r in body["history"])
    # Free again once the group is done.
    again = await client.post(f"/v1/calls/{call.call_id}/evaluations/rerun", headers={**h, **idem()})
    assert again.status_code == 202


async def test_rerun_refused_for_unfinished_call(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    call = await scripted_call(runtime, account.workspace_id, run_jobs=False)
    r = await client.post(
        f"/v1/calls/{call.call_id}/evaluations/rerun", headers={**account.headers, **idem()}
    )
    assert r.status_code == 409 and r.json()["code"] == "call_not_completed"
