"""Test run jobs (008 T035): dispatch each case to the text runner, judge each reply.

* ``dispatch_test_case(workspace_id, test_run_id, test_case_id)`` takes a slot of the workspace
  semaphore and enqueues ``run_single_turn`` on the ``textsim`` queue; without a free slot it
  re-enqueues itself after 5 s. A balance at or below zero fails the case as ``error``
  ("insufficient credit").
* ``judge_result(workspace_id, test_run_id, test_case_id)`` judges a reply through 007's model
  client (``judge.py``), stores the verdict and finishes the run when it was the last result;
  finishing records the single ``testing.run`` charge.
"""

from __future__ import annotations

import logging
from typing import Any

from callwright_contract.values import RUN_SINGLE_TURN

from app.billing import service as billing
from app.core.db import Database
from app.evals.runtime import runtime
from app.simulator import dispatch
from app.simulator.charges import merge_usage
from app.test_runs import judge, service
from app.test_runs.models import TestResult

logger = logging.getLogger(__name__)
DISPATCH_TEST_CASE = "dispatch_test_case"
JUDGE_RESULT = "judge_result"


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
