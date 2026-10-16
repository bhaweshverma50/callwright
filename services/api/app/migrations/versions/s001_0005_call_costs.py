"""Per-call cost breakdowns (T070). The FK to calls is added by 003.

Revision ID: s001_0005
Revises: s001_0004
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s001_0005"
down_revision = "s001_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE call_costs (
      call_id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      catalog_version integer NOT NULL REFERENCES pricing_catalog_versions(version),
      duration_ms bigint NOT NULL CHECK (duration_ms >= 0),
      billed_seconds integer NOT NULL CHECK (billed_seconds >= 0),
      duration_minutes numeric(18,6) NOT NULL,
      lines jsonb NOT NULL,
      total_usd numeric(18,6) NOT NULL CHECK (total_usd >= 0),
      raw_cost_usd numeric(18,6) NOT NULL CHECK (raw_cost_usd >= 0),
      txn_id text REFERENCES credit_transactions(id),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_call_costs_workspace ON call_costs (workspace_id, created_at DESC);
    ALTER TABLE call_costs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE call_costs FORCE ROW LEVEL SECURITY;
    CREATE POLICY call_costs_tenant ON call_costs
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON call_costs TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
