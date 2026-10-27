"""Review queue (007 T065; FR-023 to FR-025, research R8).

Calls the viewer has not labelled (a teammate's label does not hide a call), of origin live,
completed, ended within the lookback window, optionally for one agent. Counts come from the
current completed pass or fail runs.

* random: stable order for the viewer within a UTC day (``md5(call_id || user_id || date)``);
* failed: at least one failing run, most failures first;
* disagreement: at least one pass and one fail, closest to an even split first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Strategy = Literal["random", "failed", "disagreement"]

_BASE = """
with scope as (
  select c.id, c.agent_id, a.name as agent_name, c.ended_at, coalesce(c.billable_seconds, 0) as duration_s,
         c.sentiment, coalesce(agg.p, 0) as p, coalesce(agg.f, 0) as f
    from calls c
    join agents a on a.id = c.agent_id
    left join lateral (
      select count(*) filter (where cur.verdict = 'pass') as p,
             count(*) filter (where cur.verdict = 'fail') as f
        from (
          select distinct on (r.evaluator_id) r.status, r.verdict
            from evaluator_runs r
           where r.call_id = c.id and r.workspace_id = c.workspace_id and r.superseded_at is null
           order by r.evaluator_id, r.created_at desc
        ) cur
       where cur.status = 'completed'
    ) agg on true
   where c.origin = 'live' and c.status in ('completed', 'voicemail') and c.ended_at >= :since
     {agent}
     and not exists (select 1 from annotations n where n.call_id = c.id and n.user_id = :uid)
)
"""

_STRATEGY = {
    "random": ("true", "md5(scope.id || :uid || :day)"),
    "failed": ("scope.f >= 1", "scope.f desc, scope.ended_at desc"),
    "disagreement": ("scope.p >= 1 and scope.f >= 1", "abs(scope.p - scope.f) asc, scope.ended_at desc"),
}


def _params(
    user_id: str, agent_id: str | None, lookback_days: int, now: datetime | None
) -> tuple[str, dict[str, Any]]:
    now = now or datetime.now(UTC)
    params: dict[str, Any] = {
        "since": now - timedelta(days=lookback_days),
        "uid": user_id,
        "day": now.date().isoformat(),
    }
    agent = ""
    if agent_id:
        agent, params["agent"] = "and c.agent_id = :agent", agent_id
    return _BASE.format(agent=agent), params


async def queue(
    session: AsyncSession,
    *,
    user_id: str,
    strategy: Strategy,
    agent_id: str | None,
    lookback_days: int,
    limit: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    base, params = _params(user_id, agent_id, lookback_days, now)
    where, order = _STRATEGY[strategy]
    params["limit"] = limit
    rows = (
        await session.execute(
            text(f"{base} select * from scope where {where} order by {order} limit :limit"),  # noqa: S608
            params,
        )
    ).mappings()
    return [
        {
            "call_id": r["id"],
            "agent_id": r["agent_id"],
            "agent_name": r["agent_name"],
            "ended_at": r["ended_at"].isoformat(),
            "duration_s": int(r["duration_s"]),
            "sentiment": r["sentiment"],
            "eval_count": int(r["p"]) + int(r["f"]),
            "pass_count": int(r["p"]),
            "fail_count": int(r["f"]),
        }
        for r in rows
    ]


async def summary(
    session: AsyncSession,
    *,
    user_id: str,
    agent_id: str | None,
    lookback_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    base, params = _params(user_id, agent_id, lookback_days, now)
    row = (
        (
            await session.execute(
                text(
                    f"{base} select count(*) as random, count(*) filter (where f >= 1) as failed, "  # noqa: S608
                    "count(*) filter (where p >= 1 and f >= 1) as disagreement from scope"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    return {
        "random": int(row["random"]),
        "failed": int(row["failed"]),
        "disagreement": int(row["disagreement"]),
    }
