"""Recordings stuck in ``recording``: the sweep asks LiveKit about them when a webhook was lost."""

from __future__ import annotations

from alembic import op

revision = "s003_0003"
down_revision = "s007_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION calls_recording_pending(p_older_s integer)
    RETURNS TABLE (call_id text, workspace_id text, egress_id text, ended_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id, egress_id, ended_at FROM calls
      WHERE recording_status = 'recording' AND egress_id IS NOT NULL
        AND ended_at < now() - make_interval(secs => p_older_s)
      ORDER BY ended_at
      LIMIT 100
    $$;
    REVOKE ALL ON FUNCTION calls_recording_pending(integer) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION calls_recording_pending(integer) TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
