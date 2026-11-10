"""Issue reads, lifecycle guards, dismissal and post-apply tracking (009 T010, T012, T031, T048,
T050, T051, T060; spec FR-005, FR-019, FR-020, FR-023, FR-024, FR-026).

The status machine lives in ``lifecycle.py`` and the charge helper in ``charges.py`` (both
re-exported here); fix revisions in ``revisions.py``, validation in ``validation.py`` and apply in
``apply.py``. Every function takes a session scoped to the workspace (RLS).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions.canonical import content_hash
from app.agent_versions.models import AgentVersion
from app.agents.models import Agent
from app.agents.schemas import upcast
from app.agents.versions import draft_part
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import is_valid_id
from app.evals.current import current_runs_sql
from app.issues import kinds
from app.issues.charges import charge, detect_key, draft_key  # noqa: F401  (re-exported)
from app.issues.lifecycle import FINAL, transition
from app.issues.models import Issue, IssueFix, IssueSample, IssueValidation
from app.simulator.scorecard import display_pp, display_rate

READY_AFTER = 10
STATUS_FILTERS = ("all", "open", "validating", "validated", "applied", "dismissed")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


async def get_issue(session: AsyncSession, issue_id: str, *, lock: bool = False) -> Issue:
    if not is_valid_id(issue_id, "iss"):
        raise not_found("issue")
    query = select(Issue).where(Issue.id == issue_id)
    if lock:
        query = query.with_for_update()
    issue = (await session.execute(query)).scalar_one_or_none()
    if issue is None:
        raise not_found("issue")
    return issue


async def agent_of(session: AsyncSession, issue: Issue) -> Agent:
    agent = await session.get(Agent, issue.agent_id)
    assert agent is not None
    return agent


def agent_deleted() -> ProblemError:
    return ProblemError(
        409,
        "agent_deleted",
        "Agent deleted",
        "This issue's agent was deleted, so the issue is read-only.",
    )


async def require_live_agent(session: AsyncSession, issue: Issue) -> Agent:
    agent = await agent_of(session, issue)
    if agent.deleted_at is not None:
        raise agent_deleted()
    return agent


async def fixes_of(session: AsyncSession, issue_id: str) -> list[IssueFix]:
    rows = await session.execute(
        select(IssueFix).where(IssueFix.issue_id == issue_id).order_by(IssueFix.revision.desc())
    )
    return list(rows.scalars())


async def current_fix(session: AsyncSession, issue: Issue) -> IssueFix | None:
    if issue.current_fix_revision is None:
        return None
    return await session.get(IssueFix, (issue.id, issue.current_fix_revision))


async def validations_of(session: AsyncSession, issue_id: str) -> list[IssueValidation]:
    rows = await session.execute(
        select(IssueValidation)
        .where(IssueValidation.issue_id == issue_id)
        .order_by(IssueValidation.attempt.desc())
    )
    return list(rows.scalars())


async def latest_validation(session: AsyncSession, issue_id: str) -> IssueValidation | None:
    rows = await validations_of(session, issue_id)
    return rows[0] if rows else None


async def latest_for_revision(session: AsyncSession, issue_id: str, revision: int) -> IssueValidation | None:
    return (
        await session.execute(
            select(IssueValidation)
            .where(IssueValidation.issue_id == issue_id, IssueValidation.fix_revision == revision)
            .order_by(IssueValidation.attempt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def running_validation(session: AsyncSession, issue_id: str) -> IssueValidation | None:
    return (
        await session.execute(
            select(IssueValidation)
            .where(IssueValidation.issue_id == issue_id, IssueValidation.status == "running")
            .with_for_update()
        )
    ).scalar_one_or_none()


def summary_view(issue: Issue, current_kind: str | None = None) -> dict[str, Any]:
    return {
        "issue_id": issue.id,
        "agent_id": issue.agent_id,
        "agent_type": issue.agent_type,
        "title": issue.title,
        "evaluator_id": issue.evaluator_id,
        "evaluator_name": issue.evaluator_name,
        "evaluator_display_name": issue.evaluator_display_name,
        "flow_node_id": issue.flow_node_id,
        "flow_node_label": issue.flow_node_label,
        "status": issue.status,
        "origin": issue.origin,
        "affected_call_count": issue.affected_call_count,
        "current_version_call_count": issue.current_version_call_count,
        "calibration_warning": issue.calibration_warning,
        "current_fix_kind": current_kind,
        "recurrence_of": issue.recurrence_of,
        "first_seen_at": issue.first_seen_at.isoformat(),
        "last_seen_at": issue.last_seen_at.isoformat(),
    }


def sample_view(sample: IssueSample) -> dict[str, Any]:
    return {
        "call_id": sample.call_id,
        "reason_excerpt": sample.reason_excerpt,
        "evaluator_result_ids": list(sample.evaluator_result_ids or []),
        "agent_version_id": sample.agent_version_id or "",
        "call_origin": sample.call_origin,
        "base_call_id": sample.base_call_id,
        "failed_at": sample.failed_at.isoformat(),
    }


def fix_view(fix: IssueFix, current_revision: int | None) -> dict[str, Any]:
    return {
        "revision": fix.revision,
        "kind": fix.kind,
        "payload": dict(fix.payload or {}),
        "rationale": fix.rationale,
        "source": fix.source,
        "guidance": fix.guidance,
        "status": fix.status,
        "is_current": fix.revision == current_revision,
        "base_agent_version_id": fix.base_agent_version_id,
        "base_config_hash": fix.base_config_hash,
        "variant_config_hash": fix.variant_config_hash,
        "diff": list(fix.diff or []),
        "cost_usd": _money(fix.cost_usd),
        "created_at": fix.created_at.isoformat(),
    }


def validation_view(v: IssueValidation) -> dict[str, Any]:
    return {
        "attempt": v.attempt,
        "fix_revision": v.fix_revision,
        "auto": v.auto,
        "mode": v.mode,
        "status": v.status,
        "decision": v.decision,
        "reasons": list(v.reasons or []),
        "thresholds": {
            "min_improvement_pp": float(v.min_improvement_pp),
            "max_regression_pp": float(v.max_regression_pp),
            "min_sample": v.min_sample,
        },
        "base_agent_version_id": v.base_agent_version_id,
        "base_config_hash": v.base_config_hash,
        "variant_config_hash": v.variant_config_hash,
        "affected_call_ids": list(v.affected_call_ids or []),
        "guard_call_ids": list(v.guard_call_ids or []),
        "control_experiment_id": v.control_experiment_id,
        "treatment_experiment_id": v.treatment_experiment_id,
        "headline": dict(v.headline) if v.headline else None,
        "evaluator_results": list(v.evaluator_results or []),
        "treatment_runs_total": v.treatment_runs_total,
        "treatment_runs_failed": v.treatment_runs_failed,
        "estimated_cost_usd": _money(v.estimated_cost_usd),
        "cost_usd": _money(v.cost_usd),
        "started_at": v.started_at.isoformat(),
        "finished_at": _iso(v.finished_at),
    }


async def samples(
    session: AsyncSession, issue_id: str, *, page: int = 1, page_size: int = 50
) -> tuple[list[IssueSample], int]:
    where = [IssueSample.issue_id == issue_id]
    total = int(
        (await session.execute(select(func.count()).select_from(IssueSample).where(*where))).scalar_one()
    )
    rows = await session.execute(
        select(IssueSample)
        .where(*where)
        .order_by(IssueSample.failed_at.desc(), IssueSample.call_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars()), total


def _without_flow(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in config.items() if k != "flow"}


async def draft_matches(session: AsyncSession, agent: Agent, version_id: str) -> bool:
    """The agent's saved draft has no changes since ``version_id`` (flow graph included)."""
    version = await session.get(AgentVersion, version_id)
    if version is None:
        return False
    version_config = upcast(version.config)
    saved = content_hash(_without_flow(draft_part(upcast(agent.draft_config))))
    if saved != content_hash(_without_flow(draft_part(version_config))):
        return False
    if agent.type == "flow":
        from app.flows import compiler
        from app.flows import service as flows

        flow = await flows.flow_for_agent(session, agent.id)
        block = version_config.get("flow") if isinstance(version_config.get("flow"), dict) else {}
        graph = (block or {}).get("graph")
        if flow is None or not isinstance(graph, dict):
            return flow is None and not graph
        return compiler.graph_hash(flow.graph) == compiler.graph_hash(graph)
    return True


async def apply_blockers(
    session: AsyncSession, issue: Issue, agent: Agent, fix: IssueFix | None
) -> list[str]:
    if issue.status in FINAL or agent.deleted_at is not None:
        return ["wrong_status"]
    if fix is not None and fix.status == "advisory":
        return ["advisory_fix"]
    if fix is None or issue.status != "validated":
        return ["no_passing_validation"]
    attempt = await latest_for_revision(session, issue.id, fix.revision)
    if attempt is None or attempt.status != "completed" or attempt.decision != "passed":
        return ["no_passing_validation"]
    blockers = []
    if agent.pinned_version_id != attempt.base_agent_version_id:
        blockers.append("base_version_changed")
    if not await draft_matches(session, agent, attempt.base_agent_version_id):
        blockers.append("draft_changed")
    return blockers


_HEADLINE_SQL = (
    "select cur.verdict from ("  # noqa: S608
    + current_runs_sql(
        "and r.evaluator_id = :evaluator and c.agent_id = :agent and c.origin = 'live' "
        "and c.status = 'completed' and c.agent_version_id = :version and c.ended_at >= :since "
        "and c.ended_at < :until",
        columns="r.call_id, r.status, r.verdict",
        join_calls=True,
    )
    + ") cur where cur.status = 'completed' and cur.verdict in ('pass', 'fail')"
)


async def _side(
    session: AsyncSession, issue: Issue, version_id: str, since: datetime, until: datetime
) -> dict[str, Any]:
    verdicts = list(
        (
            await session.execute(
                text(_HEADLINE_SQL),
                {
                    "evaluator": issue.evaluator_id,
                    "agent": issue.agent_id,
                    "version": version_id,
                    "since": since,
                    "until": until,
                },
            )
        ).scalars()
    )
    n = len(verdicts)
    passes = sum(1 for v in verdicts if v == "pass")
    from fractions import Fraction

    rate = Fraction(passes, n) if n else None
    return {"agent_version_id": version_id, "n": n, "passes": passes, "rate": rate}


async def post_apply(session: AsyncSession, issue: Issue) -> dict[str, Any] | None:
    if issue.status != "applied" or issue.applied_at is None or issue.applied_agent_version_id is None:
        return None
    attempt = None
    if issue.applied_fix_revision is not None:
        attempt = await latest_for_revision(session, issue.id, issue.applied_fix_revision)
    base_version = attempt.base_agent_version_id if attempt else None
    applied = issue.applied_at
    after = await _side(
        session, issue, issue.applied_agent_version_id, applied, datetime.now(UTC) + timedelta(days=1)
    )
    before = (
        await _side(session, issue, base_version, applied - timedelta(days=issue.window_days), applied)
        if base_version
        else {"agent_version_id": "", "n": 0, "passes": 0, "rate": None}
    )
    delta = (
        100 * (after["rate"] - before["rate"])
        if after["rate"] is not None and before["rate"] is not None
        else None
    )
    return {
        "ready": after["n"] >= READY_AFTER,
        "before": {**before, "rate": display_rate(before["rate"])},  # type: ignore[arg-type]
        "after": {**after, "rate": display_rate(after["rate"])},
        "delta_pp": display_pp(delta),
    }


async def detail_view(session: AsyncSession, issue: Issue) -> dict[str, Any]:
    agent = await agent_of(session, issue)
    fix = await current_fix(session, issue)
    latest = await latest_validation(session, issue.id)
    blockers = await apply_blockers(session, issue, agent, fix)
    preview, _ = await samples(session, issue.id, page_size=5)
    allowed = kinds.allowed_kinds(issue.agent_type, issue.flow_node_id)
    return {
        **summary_view(issue, fix.kind if fix else None),
        "description": issue.description,
        "suspected_cause": issue.suspected_cause,
        "evaluator_version": issue.evaluator_version,
        "window_days": issue.window_days,
        "allowed_fix_kinds": allowed,
        "recommended_fix_kind": allowed[0],
        "current_fix": fix_view(fix, issue.current_fix_revision) if fix else None,
        "latest_validation": validation_view(latest) if latest else None,
        "can_apply": not blockers,
        "apply_blockers": blockers,
        "applied_agent_version_id": issue.applied_agent_version_id,
        "applied_at": _iso(issue.applied_at),
        "post_apply": await post_apply(session, issue),
        "dismiss_reason": issue.dismiss_reason,
        "dismiss_note": issue.dismiss_note,
        "duplicate_of": issue.duplicate_of,
        "dismissed_at": _iso(issue.dismissed_at),
        "sample_preview": [sample_view(s) for s in preview],
    }


async def list_issues(
    session: AsyncSession,
    *,
    agent_id: str | None,
    status: str,
    scope: str,
    window_days: int | None,
    applied_agent_version_id: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    where = []
    if agent_id:
        where.append(Issue.agent_id == agent_id)
    if status == "all":
        where.append(Issue.status != "dismissed")
    else:
        where.append(Issue.status == status)
    if scope == "real":
        where.append(Issue.origin != "simulated")
    if window_days:
        where.append(Issue.last_seen_at >= datetime.now(UTC) - timedelta(days=window_days))
    if applied_agent_version_id:
        where.append(Issue.applied_agent_version_id == applied_agent_version_id)
    total = int((await session.execute(select(func.count()).select_from(Issue).where(*where))).scalar_one())
    rows = list(
        (
            await session.execute(
                select(Issue)
                .where(*where)
                .order_by(Issue.affected_call_count.desc(), Issue.last_seen_at.desc(), Issue.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    kinds_by_issue: dict[str, str] = {}
    keyed = [(i.id, i.current_fix_revision) for i in rows if i.current_fix_revision is not None]
    if keyed:
        found = await session.execute(
            select(IssueFix.issue_id, IssueFix.revision, IssueFix.kind).where(
                IssueFix.issue_id.in_([k for k, _ in keyed])
            )
        )
        wanted = set(keyed)
        kinds_by_issue = {i: k for i, r, k in found.all() if (i, r) in wanted}
    return [summary_view(i, kinds_by_issue.get(i.id)) for i in rows], total


async def dismiss(
    session: AsyncSession,
    issue_id: str,
    *,
    reason: str,
    note: str | None,
    duplicate_of: str | None,
    user_id: str | None,
) -> tuple[Issue, Any]:
    """Dismiss an issue; a running validation is cancelled (returned so the caller can cancel its
    batches after commit)."""
    from app.issues import validation as validations

    issue = await get_issue(session, issue_id, lock=True)
    await require_live_agent(session, issue)
    note = (note or "").strip() or None
    if reason == "other" and not note:
        raise validation_failed([field_error("/note", "required", "Say why you are dismissing this issue.")])
    if reason == "duplicate":
        if not duplicate_of:
            raise validation_failed(
                [field_error("/duplicate_of", "required", "Choose the issue this one duplicates.")]
            )
        target = await session.get(Issue, duplicate_of) if is_valid_id(duplicate_of, "iss") else None
        if target is None or target.agent_id != issue.agent_id or target.id == issue.id:
            raise validation_failed(
                [field_error("/duplicate_of", "invalid_format", "Choose another issue of the same agent.")]
            )
    else:
        duplicate_of = None
    final = transition(issue.status, "dismiss")
    cancelled = await validations.cancel_running(session, issue, reason="dismissed")
    now = datetime.now(UTC)
    issue.status = final
    issue.dismiss_reason = reason
    issue.dismiss_note = note
    issue.duplicate_of = duplicate_of
    issue.dismissed_at = now
    issue.dismissed_by = user_id
    issue.updated_at = now
    await session.flush()
    return issue, cancelled
