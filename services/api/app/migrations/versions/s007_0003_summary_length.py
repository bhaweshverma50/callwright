"""Call summaries up to 1200 characters (first line plus Details, Actions, Outcome, Next step)."""

from __future__ import annotations

from alembic import op

revision = "s007_0003"
down_revision = "s009_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE call_analyses DROP CONSTRAINT IF EXISTS call_analyses_summary_check;
    ALTER TABLE call_analyses ADD CONSTRAINT call_analyses_summary_check
      CHECK (char_length(summary) <= 1200);
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
