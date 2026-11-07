"""Validation of a fix with control and treatment batches (009 T038 to T040; spec FR-012 to
FR-018, research R2, R7).

* ``select_calls``: up to ``affected_limit`` of the issue's sample calls that can still be
  simulated (simulated samples map to their base call; standalone persona simulations and purged
  calls are skipped), plus up to ``guard_limit`` recent live calls of the agent outside the issue
  that passed the headline evaluator. Fewer usable affected calls than ``min_sample`` is refused
  (422 ``not_enough_calls``).
* ``start``: two 008 batches over the same calls with ``source = issue_validation``: control
  runs the published version, treatment a variant with the fix applied. The validated
  configuration is the treatment batch's snapshot; its hash is written to the attempt and the fix,
  so apply can only ever publish exactly what was validated.
* ``finalize``: once both batches are final and their simulated calls are evaluated (or
  ``EVAL_WAIT_S`` passed), pairs the verdicts per evaluator and call set with 008's
  ``pair_verdicts``, runs the keep rule and writes the evidence once.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import versions
from app.agents.models import Agent
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError
from app.evals.views import LATEST_CURRENT
from app.evaluators.models import EvaluatorRow
from app.evaluators.settings import judge_models
from app.issues import validation_rule as rule
from app.issues.fixes import FixError, apply_fix
from app.issues.lifecycle import transition
from app.issues.models import Issue, IssueFix, IssueSample, IssueValidation
from app.issues.revisions import not_published, problem
from app.issues.service import current_fix, get_issue, require_live_agent, running_validation
from app.llms.client import billable_cost, token_cost
from app.simulator import service as sim
from app.simulator.scorecard import VerdictRow, collapse, display_pp, display_rate, pair_verdicts
from app.testing import calls as sim_calls

logger = logging.getLogger(__name__)
SOURCE = "issue_validation"
EVAL_WAIT_S = 20 * 60
RETRY_S = 15.0
VALIDATABLE = ("draft", "failed", "inconclusive", "passed")
SETS: tuple[rule.Set, ...] = ("affected", "guard", "combined")


@dataclass(frozen=True)
class Thresholds:
    min_improvement_pp: float = 10
    max_regression_pp: float = 5
    min_sample: int = 5

    def exact(self) -> rule.Thresholds:
        return rule.Thresholds(
            Fraction(str(self.min_improvement_pp)), Fraction(str(self.max_regression_pp)), self.min_sample
        )


@dataclass(frozen=True)
class Request:
    mode: str = "persona"
    affected_limit: int = 20
    guard_limit: int = 10
    thresholds: Thresholds = field(default_factory=Thresholds)

    @classmethod
    def of(cls, body: Mapping[str, Any]) -> Request:
        """From a validated ``ValidationBody`` dump (every field present with its default)."""
        return cls(
            mode=str(body["mode"]),
            affected_limit=int(body["affected_limit"]),
            guard_limit=int(body["guard_limit"]),
            thresholds=Thresholds(
                float(body["min_improvement_pp"]), float(body["max_regression_pp"]), int(body["min_sample"])
            ),
        )


# Call selection (T038) -------------------------------------------------------------------------


@dataclass
class Selection:
    affected: list[str]
    guard: list[str]
    skipped: int


def not_enough_calls(usable: int, needed: int) -> ProblemError:
    return ProblemError(
        422,
        "not_enough_calls",
        "Not enough calls to validate",
        f"Only {usable} of this issue's calls can still be simulated and at least {needed} are needed. "
        "Run detection again later, or lower the minimum sample.",
        extra={"usable_calls": usable, "min_sample": needed},
    )


async def select_calls(
    session: AsyncSession, issue: Issue, *, affected_limit: int, guard_limit: int, min_sample: int
) -> Selection:
    rows = list(
        (
            await session.execute(
                select(IssueSample.call_id, IssueSample.call_origin, IssueSample.base_call_id)
                .where(IssueSample.issue_id == issue.id)
                .order_by(IssueSample.failed_at.desc(), IssueSample.call_id)
            )
        ).all()
    )
    wanted: list[str] = []
    for call_id, origin, base_call_id in rows:
        target = call_id if origin == "live" else base_call_id
        if target and target not in wanted:
            wanted.append(target)
    calls = await sim_calls.load_calls(session, wanted)
    usable = [c for c in wanted if sim_calls.call_problem(calls.get(c), issue.agent_id) is None]
    affected = usable[:affected_limit]
    if len(affected) < min_sample:
        raise not_enough_calls(len(affected), min_sample)
    exclude = {c for c, _, _ in rows} | {b for _, _, b in rows if b} | set(affected)
    guard: list[str] = []
    if guard_limit > 0:
        since = datetime.now(UTC) - timedelta(days=issue.window_days)
        sql = (
            "select c.id from calls c join ("  # noqa: S608
            + LATEST_CURRENT.format(where="and r.evaluator_id = :evaluator")
            + ") r on r.call_id = c.id where c.agent_id = :agent and c.origin = 'live' "
            "and c.status = 'completed' and c.ended_at >= :since and r.status = 'completed' "
            "and r.verdict = 'pass' and not (c.id = any(:exclude)) order by c.ended_at desc, c.id limit :n"
        )
        found = list(
            (
                await session.execute(
                    text(sql),
                    {
                        "evaluator": issue.evaluator_id,
                        "agent": issue.agent_id,
                        "since": since,
                        "exclude": list(exclude),
                        "n": guard_limit * 3,
                    },
                )
            ).scalars()
        )
        loaded = await sim_calls.load_calls(session, found)
        guard = [c for c in found if sim_calls.call_problem(loaded.get(c), issue.agent_id) is None][
            :guard_limit
        ]
    return Selection(affected, guard, len(wanted) - len(usable))


# Estimate --------------------------------------------------------------------------------------


async def estimate_cost(
    session: AsyncSession, agent: Agent, settings: Settings, mode: str, run_count: int
) -> Decimal:
    from app.evals.service import est_cost, resolve_all
    from app.simulator.preflight import EXTRACTION_TOKENS, per_run_cost

    model = settings.simulator_model
    per_run = await per_run_cost(session, agent.id, mode, model)
    if mode == "persona":
        per_run += billable_cost(token_cost(model.partition("/")[2] or model, *EXTRACTION_TOKENS))
    models = judge_models(settings)
    for r in await resolve_all(session, agent, models):
        if r.enabled:
            per_run += Decimal(str(est_cost(r.row, r.values, models) or 0))
    return (per_run * run_count).quantize(Decimal("0.000001"))


def estimate_view(
    selection: Selection, cost: Decimal, missing: Sequence[Mapping[str, Any]], guard_limit: int
) -> dict[str, Any]:
    warnings = []
    if selection.skipped:
        warnings.append(
            f"{selection.skipped} of this issue's calls can no longer be simulated and are left out."
        )
    if guard_limit and not selection.guard:
        warnings.append(
            "No recent calls passed this check, so side effects are checked on the affected calls only."
        )
    elif guard_limit and len(selection.guard) < guard_limit:
        warnings.append(
            f"Only {len(selection.guard)} recent calls passed this check to guard against side effects."
        )
    if missing:
        warnings.append(
            "Tools without a mock response answer with the recorded output when there is one, otherwise "
            "with a generated stand-in."
        )
    return {
        "affected_calls": len(selection.affected),
        "guard_calls": len(selection.guard),
        "simulations": 2 * (len(selection.affected) + len(selection.guard)),
        "estimated_cost_usd": float(cost),
        "tools_missing_mock": [str(m.get("name")) for m in missing],
        "warnings": warnings,
    }


# Start (T039) ----------------------------------------------------------------------------------


@dataclass
class Prepared:
    issue: Issue
    agent: Agent
    fix: IssueFix | None
    base: versions.AgentSnapshot
    variant: dict[str, Any]
    selection: Selection
    estimate: dict[str, Any]
    cost: Decimal


def advisory_fix() -> ProblemError:
    return ProblemError(
        409,
        "advisory_fix",
        "Advisory fix",
        "This fix only lists topics no knowledge base covers. Add the content to a knowledge base, "
        "then draft a fix that attaches it.",
    )


def no_fix() -> ProblemError:
    return ProblemError(409, "no_fix", "No fix yet", "Draft a fix for this issue first, then validate it.")


async def prepare(
    session: AsyncSession,
    settings: Settings,
    issue_id: str,
    req: Request,
    *,
    lock: bool,
    estimate_only: bool = False,
) -> Prepared:
    """Checks and the estimate. ``estimate_only`` (dry runs) also works before a fix exists or
    for an advisory fix, so "Draft and validate" can show its cost first; the estimate then uses
    the published configuration."""
    from app.issues.revisions import resolve_knowledge
    from app.simulator.preflight import tools_missing_mock

    issue = await get_issue(session, issue_id, lock=lock)
    agent = await require_live_agent(session, issue)
    transition(issue.status, "validate")
    fix = await current_fix(session, issue)
    usable = fix is not None and fix.status in VALIDATABLE
    if not estimate_only:
        if fix is None:
            raise no_fix()
        if fix.status == "advisory":
            raise advisory_fix()
        if not usable:
            raise ProblemError(
                409,
                "wrong_status",
                "Fix cannot be validated",
                f"This fix is {fix.status} and cannot be validated.",
            )
    if agent.pinned_version_id is None:
        raise not_published()
    base = await versions.get_snapshot(session, agent.pinned_version_id)
    variant = dict(base.config)
    if usable and fix is not None:
        try:
            variant = apply_fix(base.config, fix.kind, fix.payload)
        except FixError as exc:
            raise problem(exc) from exc
        variant = await resolve_knowledge(session, fix.kind, variant)
    selection = await select_calls(
        session,
        issue,
        affected_limit=req.affected_limit,
        guard_limit=req.guard_limit,
        min_sample=req.thresholds.min_sample,
    )
    runs = 2 * (len(selection.affected) + len(selection.guard))
    cost = await estimate_cost(session, agent, settings, req.mode, runs)
    estimate = estimate_view(selection, cost, tools_missing_mock(variant), req.guard_limit)
    return Prepared(issue, agent, fix, base, variant, selection, estimate, cost)


@dataclass
class Started:
    attempt: IssueValidation
    run_ids: list[str]


async def start(
    session: AsyncSession,
    settings: Settings,
    prepared: Prepared,
    req: Request,
    *,
    auto: bool,
    user_id: str | None,
) -> Started:
    issue, fix, base = prepared.issue, prepared.fix, prepared.base
    assert fix is not None, "prepare() refuses a validation without a fix"
    ids = prepared.selection.affected + prepared.selection.guard
    name = issue.title[:90]
    control, control_runs = await sim.start_experiment(
        session,
        settings,
        workspace_id=issue.workspace_id,
        agent_id=issue.agent_id,
        mode=req.mode,
        target={"type": "version", "agent_version_id": base.version_id},
        base_call_ids=ids,
        name=f"{name} (control)",
        source=SOURCE,
        issue_id=issue.id,
        user_id=user_id,
    )
    treatment, treatment_runs = await sim.start_experiment(
        session,
        settings,
        workspace_id=issue.workspace_id,
        agent_id=issue.agent_id,
        mode=req.mode,
        target={
            "type": "variant",
            "config": prepared.variant,
            "agent_version_id": base.version_id,
            "label": f"Fix revision {fix.revision}",
        },
        base_call_ids=ids,
        name=f"{name} (fix)",
        source=SOURCE,
        issue_id=issue.id,
        user_id=user_id,
    )
    number = (
        int(
            (
                await session.execute(
                    select(func.coalesce(func.max(IssueValidation.attempt), 0)).where(
                        IssueValidation.issue_id == issue.id
                    )
                )
            ).scalar_one()
        )
        + 1
    )
    t = req.thresholds
    attempt = IssueValidation(
        issue_id=issue.id,
        attempt=number,
        workspace_id=issue.workspace_id,
        fix_revision=fix.revision,
        auto=auto,
        mode=req.mode,
        min_improvement_pp=Decimal(str(t.min_improvement_pp)),
        max_regression_pp=Decimal(str(t.max_regression_pp)),
        min_sample=t.min_sample,
        base_agent_version_id=base.version_id,
        base_config_hash=base.content_hash,
        variant_config_hash=treatment.config_hash,
        affected_call_ids=list(prepared.selection.affected),
        guard_call_ids=list(prepared.selection.guard),
        control_experiment_id=control.id,
        treatment_experiment_id=treatment.id,
        status="running",
        reasons=[],
        evaluator_results=[],
        estimated_cost_usd=prepared.cost,
        started_at=datetime.now(UTC),
    )
    session.add(attempt)
    fix.base_agent_version_id = base.version_id
    fix.base_config_hash = base.content_hash
    fix.variant_snapshot = dict(treatment.config_snapshot)
    fix.variant_config_hash = treatment.config_hash
    fix.status = "validating"
    issue.status = transition(issue.status, "validate")
    issue.updated_at = datetime.now(UTC)
    await session.flush()
    return Started(attempt, control_runs + treatment_runs)


# Cancel (T041, FR-018) -------------------------------------------------------------------------


@dataclass
class Cancelled:
    attempt: IssueValidation
    release: list[str]
    experiments: list[str]


async def cancel_running(
    session: AsyncSession, issue: Issue, *, reason: str = "cancelled"
) -> Cancelled | None:
    attempt = await running_validation(session, issue.id)
    if attempt is None:
        return None
    release: list[str] = []
    for exp_id in (attempt.control_experiment_id, attempt.treatment_experiment_id):
        _, ids = await sim.cancel_experiment(session, exp_id)
        release += ids
    now = datetime.now(UTC)
    attempt.status = "cancelled"
    attempt.error_message = "Dismissed while validating." if reason == "dismissed" else "Cancelled."
    attempt.finished_at = now
    fix = await session.get(IssueFix, (issue.id, attempt.fix_revision))
    if fix is not None and fix.status == "validating":
        fix.status = "draft"
    if issue.status == "validating":
        issue.status = transition(issue.status, "decided_other")
    issue.updated_at = now
    await session.flush()
    return Cancelled(attempt, release, [attempt.control_experiment_id, attempt.treatment_experiment_id])


async def after_cancel(
    state_db: Database, redis: Any, workspace_id: str, cancelled: Cancelled | None
) -> None:
    """Release runner slots of cancelled runs and fire the batches' hooks (after commit)."""
    if cancelled is None:
        return
    from app.simulator.jobs import fire_if_finished
    from app.testing import dispatch

    for run_id in cancelled.release:
        await dispatch.release(redis, workspace_id, run_id)
    for exp_id in cancelled.experiments:
        await fire_if_finished(state_db, workspace_id, exp_id)


# Finalize (T040) -------------------------------------------------------------------------------


async def attempt_for_experiment(session: AsyncSession, experiment_id: str) -> IssueValidation | None:
    return (
        await session.execute(
            select(IssueValidation)
            .where(
                or_(
                    IssueValidation.control_experiment_id == experiment_id,
                    IssueValidation.treatment_experiment_id == experiment_id,
                )
            )
            .order_by(IssueValidation.attempt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _verdicts(rows: Sequence[VerdictRow], evaluator_id: str) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for r in rows:
        if r.evaluator_id != evaluator_id:
            continue
        verdict = collapse(r)
        if verdict is not None:
            out[r.key] = (verdict, r.evaluator_version)
    return out


def paired_counts(
    evaluator_ids: Sequence[str],
    control: Sequence[VerdictRow],
    treatment: Sequence[VerdictRow],
    affected: Sequence[str],
    guard: Sequence[str],
) -> list[rule.Counts]:
    sets = {"affected": set(affected), "guard": set(guard), "combined": set(affected) | set(guard)}
    out: list[rule.Counts] = []
    for evaluator_id in evaluator_ids:
        c_all = _verdicts(control, evaluator_id)
        t_all = _verdicts(treatment, evaluator_id)
        for name in SETS:
            if name == "guard" and not guard:
                continue
            keys = sets[name]
            pairs = pair_verdicts(
                {k: v for k, v in c_all.items() if k in keys}, {k: v for k, v in t_all.items() if k in keys}
            )
            out.append(
                rule.Counts(
                    evaluator_id,
                    name,
                    pairs.n,
                    pairs.regressed + pairs.unchanged_pass,
                    pairs.improved + pairs.unchanged_pass,
                    pairs.version_mismatch,
                )
            )
    return out


def evidence_rows(
    result: rule.RuleResult,
    names: Mapping[str, EvaluatorRow],
    versions_seen: Mapping[str, int],
    headline_id: str,
) -> list[dict[str, Any]]:
    out = []
    for r in result.rows:
        has_data = r.n > 0 or r.version_mismatch > 0
        if not has_data and r.evaluator_id != headline_id:
            continue
        ev = names.get(r.evaluator_id)
        out.append(
            {
                "evaluator_id": r.evaluator_id,
                "evaluator_name": ev.display_name if ev else r.evaluator_id,
                "evaluator_version": int(
                    versions_seen.get(r.evaluator_id) or (ev.current_version if ev else 1)
                ),
                "set": r.set,
                "n": r.n,
                "control_passes": r.control_passes,
                "treatment_passes": r.treatment_passes,
                "control_rate": display_rate(r.control_rate),
                "treatment_rate": display_rate(r.treatment_rate),
                "delta_pp": display_pp(r.delta),
                "blocking": r.blocking,
                "insufficient_data": r.insufficient_data,
                "version_mismatch": r.version_mismatch,
                "headline": r.evaluator_id == headline_id,
            }
        )
    order = {"affected": 0, "guard": 1, "combined": 2}
    out.sort(key=lambda e: (not e["headline"], str(e["evaluator_name"]).casefold(), order[str(e["set"])]))
    for e in out:
        e.pop("headline")
    return out


async def _eval_cost(session: AsyncSession, call_ids: Sequence[str]) -> Decimal:
    if not call_ids:
        return Decimal(0)
    raw = (
        await session.execute(
            text(
                "select coalesce(sum(raw_cost_usd), 0) from evaluator_runs where call_id = any(:ids) "
                "and charge_txn_id is not null"
            ),
            {"ids": list(call_ids)},
        )
    ).scalar_one()
    return billable_cost(Decimal(raw)) if raw else Decimal(0)


async def finalize(
    session: AsyncSession, settings: Settings, issue_id: str, attempt_no: int, *, now: datetime | None = None
) -> str:
    """``skipped`` (nothing to do), ``waiting_batches`` (a batch is still running), ``waiting``
    (simulated calls still being evaluated), ``cancelled`` or the decision written."""
    from app.evals.service import resolve_all
    from app.simulator.comparison import verdict_rows

    now = now or datetime.now(UTC)
    attempt = (
        await session.execute(
            select(IssueValidation)
            .where(IssueValidation.issue_id == issue_id, IssueValidation.attempt == attempt_no)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if attempt is None or attempt.status != "running":
        return "skipped"
    control = await sim.get_experiment(session, attempt.control_experiment_id)
    treatment = await sim.get_experiment(session, attempt.treatment_experiment_id)
    if control.status not in sim.FINAL or treatment.status not in sim.FINAL:
        return "waiting_batches"  # the other batch's completion hook finalizes
    issue = await get_issue(session, issue_id, lock=True)
    agent = await session.get(Agent, issue.agent_id)
    fix = await session.get(IssueFix, (issue.id, attempt.fix_revision))
    if agent is None or agent.deleted_at is not None or "cancelled" in (control.status, treatment.status):
        attempt.status = "cancelled"
        attempt.error_message = (
            "The agent was deleted."
            if agent is None or agent.deleted_at is not None
            else "A batch was cancelled."
        )
        attempt.finished_at = now
        if fix is not None and fix.status == "validating":
            fix.status = "draft"
        if issue.status == "validating":
            issue.status = transition(issue.status, "decided_other")
        await session.flush()
        return "cancelled"
    runs_c = await sim.experiment_runs(session, control.id)
    runs_t = await sim.experiment_runs(session, treatment.id)
    statuses = await sim.eval_statuses(session, runs_c + runs_t)
    pending = any(s in ("pending", "running") for s in statuses.values())
    last = max(d for d in (control.finished_at, treatment.finished_at, attempt.started_at) if d is not None)
    if pending and now - last < timedelta(seconds=EVAL_WAIT_S):
        return "waiting"

    def keyed(runs: Sequence[Any]) -> dict[str, str]:
        return {
            r.output_call_id: r.base_call_id
            for r in runs
            if r.status == "completed" and r.output_call_id and r.base_call_id
        }

    control_rows = await verdict_rows(session, keyed(runs_c))
    treatment_rows = await verdict_rows(session, keyed(runs_t))
    enabled = [r.row.id for r in await resolve_all(session, agent, judge_models(settings)) if r.enabled]
    evaluator_ids = [issue.evaluator_id, *sorted(e for e in set(enabled) if e != issue.evaluator_id)]
    counts = paired_counts(
        evaluator_ids, control_rows, treatment_rows, attempt.affected_call_ids, attempt.guard_call_ids
    )
    thresholds = Thresholds(
        float(attempt.min_improvement_pp), float(attempt.max_regression_pp), attempt.min_sample
    )
    total = treatment.total_count
    failed = treatment.failed_count + treatment.cancelled_count
    result = rule.evaluate(
        issue.evaluator_id,
        counts,
        treatment_runs_total=total,
        treatment_runs_failed=failed,
        thresholds=thresholds.exact(),
    )
    rows_by_id = {
        e.id: e
        for e in (
            await session.execute(select(EvaluatorRow).where(EvaluatorRow.id.in_(evaluator_ids)))
        ).scalars()
    }
    seen: dict[str, int] = {}
    for r in treatment_rows:
        seen[r.evaluator_id] = max(seen.get(r.evaluator_id, 0), r.evaluator_version)
    evidence = evidence_rows(result, rows_by_id, seen, issue.evaluator_id)
    headline = next(
        (e for e in evidence if e["evaluator_id"] == issue.evaluator_id and e["set"] == "affected"), None
    )
    output_calls = list(keyed(runs_c)) + list(keyed(runs_t))
    cost = (
        Decimal(control.cost_usd or 0)
        + Decimal(treatment.cost_usd or 0)
        + await _eval_cost(session, output_calls)
    )
    attempt.status = "completed"
    attempt.decision = result.decision
    attempt.reasons = result.reasons
    attempt.headline = headline
    attempt.evaluator_results = evidence
    attempt.treatment_runs_total = total
    attempt.treatment_runs_failed = failed
    attempt.cost_usd = cost.quantize(Decimal("0.000001"))
    attempt.finished_at = now
    if fix is not None and fix.status == "validating":
        fix.status = result.decision
    if issue.status == "validating":
        issue.status = transition(
            issue.status, "decided_passed" if result.decision == "passed" else "decided_other"
        )
        issue.updated_at = now
    await session.flush()
    logger.info(
        "issue validation finished",
        extra={"issue_id": issue.id, "agent_id": issue.agent_id, "decision": result.decision},
    )
    return result.decision
