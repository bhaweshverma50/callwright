"""``analytics.evaluator_verdicts_v`` counts current runs only: the newest unsuperseded run per
call and evaluator (the rule of ``app.evals.current.current_runs_sql``), as the call list badge
does. Before, every unsuperseded completed run counted, including the previous result while a
rerun was in flight.

Same columns, so ``CREATE OR REPLACE`` keeps the grants.

Revision ID: s007_0004
Revises: s002_0004
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "s007_0004"
down_revision = "s002_0004"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"


def upgrade() -> None:
    op.execute(f"""
    CREATE OR REPLACE VIEW analytics.evaluator_verdicts_v WITH (security_barrier = true) AS
      SELECT r.workspace_id::text AS workspace_id, r.call_id::text AS call_id,
             r.agent_id::text AS agent_id, e.name::text AS evaluator_name,
             r.verdict::text AS verdict, r.score::numeric AS score,
             c.created_at::timestamptz AS started_at
        FROM (
          SELECT DISTINCT ON (x.call_id, x.evaluator_id) x.*
            FROM public.evaluator_runs x
           WHERE x.superseded_at IS NULL AND x.workspace_id = {WS}
           ORDER BY x.call_id, x.evaluator_id, x.created_at DESC
        ) r
        JOIN public.evaluators e ON e.id = r.evaluator_id
        JOIN public.calls c ON c.id = r.call_id
       WHERE r.status = 'completed' AND r.verdict IN ('pass', 'fail') AND c.origin = 'live';
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
