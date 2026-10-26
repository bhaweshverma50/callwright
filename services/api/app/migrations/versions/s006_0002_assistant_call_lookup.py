"""Assistant call lookups and test calls (006 follow-up): the ``analytics`` views carry every
origin with an ``origin`` column, so the assistant can answer "what did my last call cost" for a
test call. Aggregates stay live-only by default because the compiler always binds an origin filter
(``MetricQuery.origins`` defaults to ``["live"]``).

``calls_v`` also gains ``avg_latency_ms`` (the call's average end-to-end turn latency) and
``ended_at``. Columns are appended, so ``CREATE OR REPLACE`` keeps the grants. Tenancy is
unchanged: each view still filters on ``app.workspace_id``.

Revision ID: s006_0002
Revises: s004_0001
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "s006_0002"
down_revision = "s004_0001"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"


def upgrade() -> None:
    op.execute(f"""
    CREATE OR REPLACE VIEW analytics.calls_v WITH (security_barrier = true) AS
      SELECT c.id AS call_id, c.workspace_id, c.agent_id, a.name AS agent_name, c.channel, c.status,
             c.disconnect_reason, coalesce(c.sentiment, 'unknown') AS sentiment,
             c.created_at AS started_at, coalesce(c.billable_seconds, 0) AS duration_s,
             c.cost_total_usd AS cost_usd, c.origin,
             (c.latency_stats->>'e2e_avg_ms')::numeric AS avg_latency_ms, c.ended_at
        FROM public.calls c JOIN public.agents a ON a.id = c.agent_id
       WHERE c.workspace_id = {WS};

    CREATE OR REPLACE VIEW analytics.turn_latency_v WITH (security_barrier = true) AS
      SELECT e.workspace_id, e.call_id, c.agent_id, e.occurred_at, e.e2e_ms, c.origin
        FROM public.call_events e JOIN public.calls c ON c.id = e.call_id
       WHERE e.type = 'turn' AND e.turn_index > 0 AND e.e2e_ms IS NOT NULL
         AND e.workspace_id = {WS};
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
