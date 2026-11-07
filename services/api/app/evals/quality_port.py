"""007's implementation of 006's ``CallQualityPort`` (T040, FR-032, research R10).

Call list and drawer summaries, the list filter (viewer's label, evaluation status), dashboard
window statistics with headline flags, verdict diffs for the compare view and the post-call
analysis state of listed calls. Everything reads current runs (``evals.views``), so the list
filter and the row badge always agree.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, column, exists, false, not_, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_vars.models import CallAnalysis
from app.annotations.models import Annotation
from app.calls.quality_port import EvaluatorStat, QualitySummary, VerdictDiff
from app.evals import verdict_diff
from app.evals.models import AgentEvalSetting
from app.evals.scoring import EVAL_STATUSES, RunState, call_eval_status, run_counts
from app.evals.views import current_runs_sql, eval_status_sql


class QualityPort:
    async def summaries(
        self, session: AsyncSession, call_ids: Sequence[str], user_id: str
    ) -> dict[str, QualitySummary]:
        if not call_ids:
            return {}
        ids = list(call_ids)
        rows = (
            await session.execute(
                text(current_runs_sql("and r.call_id = any(:ids)", columns="r.call_id, r.status, r.verdict")),
                {"ids": ids},
            )
        ).all()
        runs: dict[str, list[RunState]] = defaultdict(list)
        for call_id, status, verdict in rows:
            runs[call_id].append(RunState(status, verdict))
        labels = dict(
            (
                await session.execute(
                    select(Annotation.call_id, Annotation.label).where(
                        Annotation.user_id == user_id, Annotation.call_id.in_(ids)
                    )
                )
            ).all()
        )
        out = {}
        for call_id in ids:
            states = runs.get(call_id, [])
            passes, fails = run_counts(states)
            out[call_id] = QualitySummary(call_eval_status(states), passes, fails, labels.get(call_id))  # type: ignore[arg-type]
        return out

    def filter_clause(
        self,
        call_id_column: Any,
        *,
        labels: Sequence[str],
        eval_statuses: Sequence[str],
        user_id: str,
    ) -> ColumnElement[bool]:
        clauses: list[ColumnElement[bool]] = []
        if labels:
            mine = select(Annotation.id).where(
                Annotation.call_id == call_id_column, Annotation.user_id == user_id
            )
            parts: list[ColumnElement[bool]] = []
            chosen = [label for label in labels if label in ("good", "bad")]
            if chosen:
                parts.append(exists(mine.where(Annotation.label.in_(chosen))))
            if "unannotated" in labels:
                parts.append(not_(exists(mine)))
            clauses.append(or_(*parts) if parts else false())
        if eval_statuses:
            statuses = text(eval_status_sql()).columns(column("call_id"), column("eval_status")).subquery()
            chosen_statuses = [s for s in eval_statuses if s in EVAL_STATUSES]
            parts = [
                call_id_column.in_(
                    select(statuses.c.call_id).where(statuses.c.eval_status.in_(chosen_statuses))
                )
            ]
            if "not_evaluated" in chosen_statuses:
                parts.append(call_id_column.not_in(select(statuses.c.call_id)))
            clauses.append(or_(*parts) if chosen_statuses else false())
        return and_(*clauses) if clauses else true()

    async def window_stats(
        self,
        session: AsyncSession,
        *,
        start: datetime,
        end: datetime,
        agent_ids: Sequence[str],
    ) -> tuple[list[EvaluatorStat], int]:
        agent_filter = "and c.agent_id = any(:agents)" if agent_ids else ""
        cur = current_runs_sql(
            f"and c.origin = 'live' and c.created_at >= :start and c.created_at < :end {agent_filter}",
            columns="r.call_id, r.evaluator_id, r.status, r.verdict, r.score",
            join_calls=True,
        )
        sql = (
            "select e.id, e.name, e.display_name, e.scope, "  # noqa: S608
            "count(*) filter (where cur.status = 'completed' and cur.verdict = 'pass'), "
            "count(*) filter (where cur.status = 'completed' and cur.verdict = 'fail'), "
            "count(*) filter (where cur.status = 'completed' and cur.verdict = 'not_applicable'), "
            "count(*) filter (where cur.status = 'completed'), "
            "count(distinct cur.call_id) filter (where cur.status = 'completed'), "
            "avg(cur.score) filter (where cur.status = 'completed' and cur.verdict in ('pass', 'fail')) "
            f"from ({cur}) cur join evaluators e on e.id = cur.evaluator_id "
            "group by e.id, e.name, e.display_name, e.scope"
        )
        params: dict[str, Any] = {"start": start, "end": end}
        if agent_ids:
            params["agents"] = list(agent_ids)
        rows = (await session.execute(text(sql), params)).all()
        headline_query = select(AgentEvalSetting.evaluator_id).where(AgentEvalSetting.is_headline.is_(True))
        if agent_ids:
            headline_query = headline_query.where(AgentEvalSetting.agent_id.in_(list(agent_ids)))
        headline = set((await session.execute(headline_query)).scalars())
        total = (
            await session.execute(
                text(f"select count(distinct cur.call_id) from ({cur}) cur where cur.status = 'completed'"),  # noqa: S608
                params,
            )
        ).scalar_one()
        stats = [
            EvaluatorStat(
                evaluator_id=r[0],
                evaluator_name=r[1],
                display_name=r[2],
                scope=r[3],
                pass_count=int(r[4]),
                fail_count=int(r[5]),
                not_applicable_count=int(r[6]),
                total_runs=int(r[7]),
                calls_evaluated=int(r[8]),
                avg_score=float(r[9]) if r[9] is not None else None,
                headline=r[0] in headline,
            )
            for r in rows
            if int(r[7]) > 0
        ]
        return sorted(stats, key=lambda s: s.display_name.casefold()), int(total or 0)

    async def verdict_diffs(
        self, session: AsyncSession, left_call_id: str, right_call_id: str
    ) -> list[VerdictDiff]:
        return list(await verdict_diff.verdict_diffs(session, left_call_id, right_call_id))

    async def analysis_states(
        self, session: AsyncSession, call_ids: Sequence[str]
    ) -> dict[str, tuple[str, str | None]]:
        if not call_ids:
            return {}
        rows = await session.execute(
            select(CallAnalysis.call_id, CallAnalysis.status, CallAnalysis.skip_reason).where(
                CallAnalysis.call_id.in_(list(call_ids))
            )
        )
        return {r.call_id: (r.status, r.skip_reason) for r in rows}
