"""Flow agents (004 T005, data-model section 1): the ``flows`` table, one row per flow agent,
holding the graph document, its revision and the last validation result. Also a partial index on
003's ``call_events`` for the flow-transition read projection (data-model section 6).

Revision ID: s004_0001
Revises: s006_0001
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "s004_0001"
down_revision = "s010_0001"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE flows (
      id text PRIMARY KEY CHECK (id ~ '^flw_[0-9A-HJKMNP-TV-Z]{{26}}$'),
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
      graph jsonb NOT NULL,
      revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
      last_validation jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      last_published_version_id text REFERENCES agent_versions(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      updated_by text,
      CONSTRAINT uq_flows_agent UNIQUE (agent_id)
    );
    CREATE INDEX ix_flows_workspace_updated ON flows (workspace_id, updated_at DESC);
    ALTER TABLE flows ENABLE ROW LEVEL SECURITY;
    ALTER TABLE flows FORCE ROW LEVEL SECURITY;
    CREATE POLICY flows_tenant ON flows
      USING (workspace_id = {WS})
      WITH CHECK (workspace_id = {WS});
    GRANT SELECT, INSERT, UPDATE, DELETE ON flows TO callwright_app;

    CREATE INDEX ix_call_events_flow ON call_events (call_id, seq) WHERE type LIKE 'flow_%';
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS ix_call_events_flow;
    DROP TABLE IF EXISTS flows;
    """)
