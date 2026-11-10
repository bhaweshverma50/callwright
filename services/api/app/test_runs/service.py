"""Test runs (008 T034; FR-007 to FR-010, US1).

Lifecycle: ``queued`` (created with one pending result per selected case, each a copy of the
case text) > ``running`` (the runner fetched a case) > ``completed`` (every result judged, the
``testing.run`` feature charge recorded). ``cancel`` moves a queued or running run to
``cancelled``: finished results stay, unfinished ones become ``error``. A result moves
``pending > running > judging > done`` (or ``cancelled``).

Counts and the case's last status use the effective status (manual override, else the judge):
see ``counts.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from callwright_contract.adapters import load_catalog
from callwright_contract.textsim import MAX_ERROR_CHARS, CaseSpec
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.billing import service as billing
from app.calls.service import runtime_values
from app.core.config import Settings
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import new_id
from app.core.pagination import page_window
from app.evaluators.settings import default_judge_model, judge_models
from app.test_cases.models import TestCase
from app.test_runs.counts import ResultState, run_counts
from app.test_runs.models import TestResult, TestRun
from app.testing.charges import charge_run, merge_usage
from app.testing.targets import agent_model, agent_type_of, require_agent, resolve_target, runnable_problem

ACTIVE = ("queued", "running")
UNFINISHED_RESULTS = ("pending", "running", "judging")


def target_view(run: TestRun) -> dict[str, Any]:
    out: dict[str, Any] = {"type": run.target_type}
    if run.target_type == "version" and run.agent_version_id:
        out["agent_version_id"] = run.agent_version_id
    return out


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def run_view(run: TestRun) -> dict[str, Any]:
    return {
        "test_run_id": run.id,
        "number": run.number,
        "agent_id": run.agent_id,
        "target": target_view(run),
        "config_hash": run.config_hash,
        "agent_model": run.agent_model,
        "judge_model": run.judge_model,
        "status": run.status,
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "errored": run.errored,
        "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
        "created_at": run.created_at.isoformat(),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def result_view(r: TestResult) -> dict[str, Any]:
    status = r.override_status or r.judge_status
    return {
        "test_case_id": r.test_case_id,
        "case_name": r.case_name,
        "category": r.category_slug,
        "user_prompt": r.user_prompt,
        "expected_behaviour": r.expected_behaviour,
        "agent_response": r.agent_response,
        "tool_calls": list(r.tool_calls or []),
        "nodes_visited": list(r.nodes_visited or []),
        "judge_status": r.judge_status,
        "judge_reasoning": r.judge_reasoning,
        "override_status": r.override_status,
        "override_note": r.override_note,
        "overridden_at": _iso(r.overridden_at),
        "status": status,
        "is_manual": r.override_status is not None,
        "error_message": r.error_message,
        "duration_ms": r.duration_ms,
    }


async def _select_cases(
    session: AsyncSession, agent_id: str, case_ids: Sequence[str] | None, category: str | None
) -> list[TestCase]:
    query = select(TestCase).where(TestCase.agent_id == agent_id)
    if case_ids:
        wanted = list(dict.fromkeys(case_ids))
        rows = list((await session.execute(query.where(TestCase.id.in_(wanted)))).scalars())
        found = {c.id for c in rows}
        missing = [i for i, c in enumerate(wanted) if c not in found]
        if missing:
            raise validation_failed(
                [
                    field_error(f"/test_case_ids/{i}", "invalid_format", "Not a test case of this agent")
                    for i in missing
                ]
            )
        order = {c: i for i, c in enumerate(wanted)}
        return sorted(rows, key=lambda c: order[c.id])
    if category:
        query = query.where(TestCase.category_slug == category)
    return list((await session.execute(query.order_by(TestCase.created_at, TestCase.id))).scalars())


async def _next_number(session: AsyncSession, agent_id: str) -> int:
    await session.execute(select(Agent.id).where(Agent.id == agent_id).with_for_update())
    current = (
        await session.execute(
            select(func.coalesce(func.max(TestRun.number), 0)).where(TestRun.agent_id == agent_id)
        )
    ).scalar_one()
    return int(current) + 1


async def start_run(
    session: AsyncSession,
    settings: Settings,
    *,
    workspace_id: str,
    user_id: str | None,
    body: Mapping[str, Any],
) -> tuple[TestRun, list[str]]:
    """Create the run and its pending results. Returns (run, case ids to dispatch)."""
    agent = await require_agent(session, str(body["agent_id"]), pointer="/agent_id")
    judge_model = str(body.get("judge_model") or default_judge_model(settings))
    if judge_model not in judge_models(settings):
        raise validation_failed(
            [field_error("/judge_model", "invalid_format", "Choose one of the judge models")]
        )
    target = await resolve_target(session, agent, body.get("target"), default="draft", allow_variant=False)
    problem = runnable_problem(agent_type_of(agent), target.config)
    if problem is not None:
        raise problem
    cases = await _select_cases(session, agent.id, body.get("test_case_ids"), body.get("category"))
    if not cases:
        raise ProblemError(
            409, "no_test_cases", "No test cases", "There are no test cases to run. Add one first."
        )
    if await billing.get_balance(session, workspace_id) <= 0:
        raise billing.insufficient_credit("Add funds to run test cases.")
    now = datetime.now(UTC)
    run = TestRun(
        id=new_id("trn"),
        workspace_id=workspace_id,
        agent_id=agent.id,
        number=await _next_number(session, agent.id),
        target_type=target.target_type,
        agent_version_id=target.agent_version_id,
        config_snapshot=target.config,
        config_hash=target.config_hash,
        agent_model=agent_model(target.config),
        judge_model=judge_model,
        status="queued",
        total=len(cases),
        usage={},
        created_by=user_id,
        created_at=now,
    )
    session.add(run)
    await session.flush()
    for position, case in enumerate(cases):
        session.add(
            TestResult(
                test_run_id=run.id,
                test_case_id=case.id,
                workspace_id=workspace_id,
                position=position,
                case_name=case.name,
                category_slug=case.category_slug,
                user_prompt=case.user_prompt,
                expected_behaviour=case.expected_behaviour,
                dynamic_variables=dict(case.dynamic_variables or {}),
                state="pending",
                tool_calls=[],
                nodes_visited=[],
                usage={},
            )
        )
    await session.flush()
    return run, [c.id for c in cases]


async def get_run(session: AsyncSession, run_id: str, *, lock: bool = False) -> TestRun:
    query = select(TestRun).where(TestRun.id == run_id)
    if lock:
        query = query.with_for_update()
    run = (await session.execute(query)).scalar_one_or_none()
    if run is None:
        raise not_found("test run")
    return run


async def results_of(session: AsyncSession, run_id: str) -> list[TestResult]:
    rows = await session.execute(
        select(TestResult).where(TestResult.test_run_id == run_id).order_by(TestResult.position)
    )
    return list(rows.scalars())


async def list_runs(
    session: AsyncSession, agent_id: str, *, page: int, page_size: int
) -> tuple[list[TestRun], int]:
    where = [TestRun.agent_id == agent_id]
    total = int((await session.execute(select(func.count()).select_from(TestRun).where(*where))).scalar_one())
    rows = await session.execute(
        select(TestRun)
        .where(*where)
        .order_by(TestRun.created_at.desc(), TestRun.id.desc())
        .slice(*page_window(page, page_size))
    )
    return list(rows.scalars()), total


async def recount(session: AsyncSession, run: TestRun) -> None:
    results = await results_of(session, run.id)
    run.passed, run.failed, run.errored = run_counts(
        ResultState(r.judge_status, r.override_status) for r in results
    )


async def update_last_status(session: AsyncSession, run: TestRun, results: Sequence[TestResult]) -> None:
    """Cases take the effective status of this run when it is their latest run (ULID order)."""
    for r in results:
        status = r.override_status or r.judge_status
        if status is None:
            continue
        await session.execute(
            text(
                "update test_cases set last_status = :status, last_run_id = :run, updated_at = updated_at "
                "where id = :case and (last_run_id is null or last_run_id <= :run)"
            ),
            {"status": status, "run": run.id, "case": r.test_case_id},
        )


async def maybe_finish(session: AsyncSession, run: TestRun) -> bool:
    """Complete the run once every result is done; charge ``testing.run`` once. Returns True
    when the run reached a final status in this call."""
    if run.status not in ACTIVE:
        return False
    results = await results_of(session, run.id)
    if any(r.state in UNFINISHED_RESULTS for r in results):
        return False
    await finish(session, run, results, status="completed")
    return True


async def finish(session: AsyncSession, run: TestRun, results: Sequence[TestResult], *, status: str) -> None:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.passed, run.failed, run.errored = run_counts(
        ResultState(r.judge_status, r.override_status) for r in results
    )
    run.usage = merge_usage(*(r.usage or {} for r in results))
    try:
        charge = await charge_run(
            session,
            workspace_id=run.workspace_id,
            run_id=run.id,
            feature_key="testing.run",
            usage=run.usage,
            ref_type="test_run",
            ref_id=run.id,
        )
        run.cost_usd = charge.billable_usd
    except ProblemError as exc:
        if exc.code != "insufficient_credit":
            raise
        run.cost_usd = Decimal(0)
        run.error_message = "Not charged: the balance ran out during the run."
    await update_last_status(session, run, results)


async def cancel(session: AsyncSession, run_id: str) -> tuple[TestRun, list[str]]:
    """Cancel; returns the run and the case ids whose runner slots must be released."""
    run = await get_run(session, run_id, lock=True)
    if run.status not in ACTIVE:
        raise ProblemError(409, "run_finished", "Run finished", "This run has already finished.")
    results = await results_of(session, run.id)
    released = []
    for r in results:
        if r.state in UNFINISHED_RESULTS:
            if r.state in ("running", "judging"):
                released.append(r.test_case_id)
            r.state = "cancelled"
            r.judge_status = "error"
            r.error_message = "Cancelled before it finished."
    await session.flush()
    await finish(session, run, results, status="cancelled")
    return run, released


async def override(
    session: AsyncSession, run_id: str, case_id: str, status: str | None, note: str | None
) -> tuple[TestResult, TestRun]:
    run = await get_run(session, run_id, lock=True)
    result = await session.get(TestResult, (run_id, case_id), with_for_update=True)
    if result is None:
        raise not_found("test result")
    if run.status in ACTIVE or result.state != "done":
        raise ProblemError(409, "run_not_finished", "Run still running", "Wait for the run to finish first.")
    result.override_status = status
    result.override_note = (note or None) if status else None
    result.overridden_at = datetime.now(UTC) if status else None
    await session.flush()
    await session.refresh(result)
    await recount(session, run)
    await update_last_status(session, run, [result])
    if status is None:
        # Clearing restores the judge's verdict as the case's status when this is its latest run.
        await session.execute(
            update(TestCase)
            .where(TestCase.id == case_id, TestCase.last_run_id == run.id)
            .values(last_status=result.judge_status)
        )
    await session.flush()
    return result, run


async def case_spec(session: AsyncSession, run_id: str, case_id: str) -> CaseSpec:
    run = await get_run(session, run_id, lock=True)
    result = await session.get(TestResult, (run_id, case_id), with_for_update=True)
    if result is None:
        raise not_found("test result")
    if run.status not in ACTIVE or result.state not in ("pending", "running"):
        raise ProblemError(409, "run_closed", "Run closed", "This test case no longer needs a run.")
    now = datetime.now(UTC)
    result.state = "running"
    if run.status == "queued":
        run.status = "running"
        run.started_at = now
    return CaseSpec(
        workspace_id=run.workspace_id,
        agent_id=run.agent_id,
        agent_type="flow" if run.config_snapshot.get("type") == "flow" else "single_prompt",
        runtime=runtime_values(run.config_snapshot, load_catalog()),
        user_prompt=result.user_prompt,
        dynamic_variables=result.dynamic_variables or {},
    )


async def record_result(session: AsyncSession, run_id: str, case_id: str, body: Mapping[str, Any]) -> str:
    """Store the runner's answer. Returns ``judge`` (judging needed), ``done`` or ``ignored``."""
    run = await get_run(session, run_id, lock=True)
    result = await session.get(TestResult, (run_id, case_id), with_for_update=True)
    if result is None:
        raise not_found("test result")
    if run.status not in ACTIVE or result.state not in ("pending", "running"):
        return "ignored"
    result.agent_response = body.get("agent_response")
    result.tool_calls = list(body.get("tool_calls") or [])
    result.nodes_visited = [str(n) for n in body.get("nodes_visited") or []]
    result.duration_ms = body.get("duration_ms")
    result.usage = merge_usage(body.get("usage") or {})
    if body.get("status") == "completed":
        result.state = "judging"
        return "judge"
    result.state = "done"
    result.judge_status = "error"
    result.error_message = str(body.get("error_message") or "The agent could not answer.")[:MAX_ERROR_CHARS]
    await session.flush()
    await maybe_finish(session, run)
    return "done"


async def fail_case(session: AsyncSession, run_id: str, case_id: str, message: str) -> None:
    """Infrastructure failure for one case (no credit, runner timeout)."""
    run = await get_run(session, run_id, lock=True)
    result = await session.get(TestResult, (run_id, case_id), with_for_update=True)
    if result is None or run.status not in ACTIVE or result.state not in UNFINISHED_RESULTS:
        return
    result.state = "done"
    result.judge_status = "error"
    result.error_message = message
    await session.flush()
    await maybe_finish(session, run)
