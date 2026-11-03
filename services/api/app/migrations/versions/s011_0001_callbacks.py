"""Scheduled callbacks (011).

* ``scheduled_callbacks``: an outbound call booked for later, by the agent during a call or
  through the API. At most one open (scheduled or placing) callback per source call.
* ``callbacks_due(now, limit)``: security definer for the placing cron, which starts without a
  workspace. It returns ids only; the cron then works inside each workspace.

Revision ID: s011_0001
Revises: s003_0004
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "s011_0001"
down_revision = "s003_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TYPE callback_status AS ENUM ('scheduled', 'placing', 'placed', 'cancelled', 'failed');
    CREATE TYPE callback_origin AS ENUM ('agent', 'api');

    CREATE TABLE scheduled_callbacks (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      phone_number_id text REFERENCES phone_numbers(id) ON DELETE SET NULL,
      from_number text NOT NULL CHECK (from_number ~ '^\\+[1-9][0-9]{6,14}$'),
      to_number text NOT NULL CHECK (to_number ~ '^\\+[1-9][0-9]{6,14}$'),
      agent_id text REFERENCES agents(id) ON DELETE SET NULL,
      scheduled_at timestamptz NOT NULL,
      timezone text NOT NULL,
      recipient_timezones text[] NOT NULL DEFAULT '{}',
      timezone_source timezone_source NOT NULL,
      note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 500),
      dynamic_variables jsonb NOT NULL DEFAULT '{}',
      source_call_id text REFERENCES calls(id) ON DELETE SET NULL,
      call_id text REFERENCES calls(id) ON DELETE SET NULL,
      created_via callback_origin NOT NULL,
      created_by_user_id text REFERENCES users(id) ON DELETE SET NULL,
      status callback_status NOT NULL DEFAULT 'scheduled',
      failure_reason text CHECK (char_length(failure_reason) <= 64),
      failure_detail text CHECK (char_length(failure_detail) <= 500),
      attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      placed_at timestamptz,
      cancelled_at timestamptz,
      CONSTRAINT scheduled_callbacks_failed_reason
        CHECK ((status = 'failed') = (failure_reason IS NOT NULL))
    );
    CREATE INDEX ix_scheduled_callbacks_workspace_time
      ON scheduled_callbacks (workspace_id, scheduled_at DESC);
    CREATE INDEX ix_scheduled_callbacks_due ON scheduled_callbacks (scheduled_at)
      WHERE status IN ('scheduled', 'placing');
    CREATE INDEX ix_scheduled_callbacks_source ON scheduled_callbacks (source_call_id)
      WHERE source_call_id IS NOT NULL;
    CREATE UNIQUE INDEX uq_scheduled_callbacks_open_source ON scheduled_callbacks (source_call_id)
      WHERE source_call_id IS NOT NULL AND status IN ('scheduled', 'placing');

    ALTER TABLE scheduled_callbacks ENABLE ROW LEVEL SECURITY;
    ALTER TABLE scheduled_callbacks FORCE ROW LEVEL SECURITY;
    CREATE POLICY scheduled_callbacks_tenant ON scheduled_callbacks
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON scheduled_callbacks TO callwright_app;

    -- Due callbacks in any workspace: scheduled and due, or stuck in placing for 2 minutes
    -- (the cron died mid-dial; a retry is safe because the call's idempotency key is the id).
    CREATE FUNCTION callbacks_due(p_now timestamptz, p_limit integer)
    RETURNS TABLE (id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id FROM scheduled_callbacks
      WHERE (status = 'scheduled' AND scheduled_at <= p_now)
         OR (status = 'placing' AND updated_at <= p_now - interval '2 minutes')
      ORDER BY scheduled_at
      LIMIT p_limit
    $$;
    REVOKE ALL ON FUNCTION callbacks_due(timestamptz, integer) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION callbacks_due(timestamptz, integer) TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
