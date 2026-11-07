"""Test run jobs (008 T035): dispatch each case to the text runner, judge each reply.

* ``dispatch_test_case(workspace_id, test_run_id, test_case_id)`` takes a slot of the workspace
  semaphore and enqueues ``run_single_turn`` on the ``textsim`` queue; without a free slot it
  re-enqueues itself after 5 s. A balance at or below zero fails the case as ``error``
  ("insufficient credit").
* ``judge_result(workspace_id, test_run_id, test_case_id)`` judges a reply through 007's model
  client (``judge.py``), stores the verdict and finishes the run when it was the last result;
  finishing records the single ``testing.run`` charge.
* ``sweep_test_results`` (cron, every minute): cases whose runner or judge never answered within
  twice ``dispatch.STALE_RUN_S`` become ``error`` so their run finishes, and release their slots.
"""

from __future__ import annotations

import logging
from typing import Any

from callwright_contract.textsim import RUN_SINGLE_TURN
from sqlalchemy import text

from app.billing import service as billing
from app.core.db import Database
from app.llms.runtime import runtime
from app.test_runs import judge, service
from app.test_runs.models import TestResult
from app.testing import dispatch
from app.testing.charges import merge_usage

logger = logging.getLogger(__name__)
DISPATCH_TEST_CASE = "dispatch_test_case"
JUDGE_RESULT = "judge_result"


SWEEP_TEST_RESULTS = "sweep_test_results"


def holder(test_run_id: str, test_case_id: str) -> str:
    return f"{test_run_id}:{test_case_id}"


async def dispatch_test_case(
    ctx: dict[str, Any], workspace_id: str, test_run_id: str, test_case_id: str
) -> str:
    db: Database = ctx["db"]
    settings = ctx["settings"]
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await service.get_run(session, test_run_id)
        result = await session.get(TestResult, (test_run_id, test_case_id))
        if result is None or run.status not in service.ACTIVE or result.state != "pending":
            return "skipped"
        if await billing.get_balance(session, workspace_id) <= 0:
            await service.fail_case(session, test_run_id, test_case_id, "insufficient credit")
            return "insufficient_credit"
    redis = ctx["redis"]
    if not await dispatch.acquire(
        redis, workspace_id, holder(test_run_id, test_case_id), settings.sim_max_concurrency
    ):
        await ctx["jobs"].enqueue(
            DISPATCH_TEST_CASE, workspace_id, test_run_id, test_case_id, defer_by_s=dispatch.RETRY_DEFER_S
        )
        return "waiting"
    await dispatch.textsim_queue(ctx).enqueue(
        RUN_SINGLE_TURN, test_run_id, test_case_id, job_id=f"textsim:{test_run_id}:{test_case_id}"
    )
    return "dispatched"


async def judge_result(ctx: dict[str, Any], workspace_id: str, test_run_id: str, test_case_id: str) -> str:
    db: Database = ctx["db"]
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await service.get_run(session, test_run_id)
        result = await session.get(TestResult, (test_run_id, test_case_id))
        if result is None or result.state != "judging":
            return "skipped"
        model = run.judge_model
        inputs = (
            result.user_prompt,
            result.expected_behaviour,
            result.agent_response,
            list(result.tool_calls or []),
        )
    rt = runtime()
    outcome = await judge.judge(
        rt.llm,
        model,
        user_prompt=inputs[0],
        expected_behaviour=inputs[1],
        agent_response=inputs[2],
        tool_calls=inputs[3],
        timeout_s=rt.settings.eval_timeout_s,
    )
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await service.get_run(session, test_run_id, lock=True)
        result = await session.get(TestResult, (test_run_id, test_case_id), with_for_update=True)
        if result is None or result.state != "judging":
            return "skipped"
        result.state = "done"
        result.judge_status = outcome.status
        result.judge_reasoning = outcome.reasoning
        result.judge_model = outcome.model
        if outcome.status == "error":
            result.error_message = outcome.reasoning
        result.usage = merge_usage(result.usage or {}, outcome.usage())
        await session.flush()
        await service.recount(session, run)
        await service.maybe_finish(session, run)
    return outcome.status


async def sweep_test_results(ctx: dict[str, Any]) -> int:
    """Fail test cases whose runner or judge went silent; returns how many were failed."""
    db: Database = ctx["db"]
    async with db.transaction() as session:
        rows = (
            await session.execute(
                text("select test_run_id, test_case_id, workspace_id from test_results_stale(:s)"),
                {"s": dispatch.STALE_RUN_S * 2},
            )
        ).all()
    for run_id, case_id, workspace_id in rows:
        async with db.transaction(workspace_id=workspace_id) as session:
            await service.fail_case(session, run_id, case_id, "The test runner stopped answering.")
        await dispatch.release(ctx["redis"], workspace_id, holder(run_id, case_id))
    return len(rows)
