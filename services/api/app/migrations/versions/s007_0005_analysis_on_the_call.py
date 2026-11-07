"""Post-call analysis is stored once, on the call (``calls.summary``, ``sentiment``,
``analysis``), which the call list, filters, dashboard, export and retention purge already read.
``call_analyses`` keeps only the run's own state (status, model, variable snapshot, cost).

The dropped columns held copies of what ``calls`` holds (both were written together).

Revision ID: s007_0005
Revises: s007_0004
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "s007_0005"
down_revision = "s007_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Summary is not copied back: the retention purge clears calls.summary on purpose.
    op.execute("""
    UPDATE calls c
       SET sentiment = coalesce(c.sentiment, a.sentiment),
           analysis = coalesce(c.analysis, a."values")
      FROM call_analyses a
     WHERE a.call_id = c.id
       AND (c.sentiment IS NULL AND a.sentiment IS NOT NULL
            OR c.analysis IS NULL AND a."values" IS NOT NULL);
    ALTER TABLE call_analyses DROP COLUMN summary, DROP COLUMN sentiment, DROP COLUMN "values";
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
