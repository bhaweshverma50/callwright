"""Skip reason ``too_short`` for post-call analysis and judge runs.

Calls under ``ANALYSIS_MIN_DURATION_S`` or with fewer caller characters than
``ANALYSIS_MIN_CALLER_CHARS`` skip the AI summary and paid judge checks after the call.
"""

from __future__ import annotations

from alembic import op

revision = "s007_0002"
down_revision = "s008_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE call_analyses DROP CONSTRAINT IF EXISTS call_analyses_skip_reason_check;
    ALTER TABLE call_analyses ADD CONSTRAINT call_analyses_skip_reason_check
      CHECK (skip_reason IN ('insufficient_credit', 'too_short'));
    ALTER TABLE evaluator_runs DROP CONSTRAINT IF EXISTS evaluator_runs_skip_reason_check;
    ALTER TABLE evaluator_runs ADD CONSTRAINT evaluator_runs_skip_reason_check
      CHECK (skip_reason IN ('insufficient_credit', 'not_applicable_agent_type', 'evaluator_disabled',
                             'not_sampled', 'too_short'));
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
