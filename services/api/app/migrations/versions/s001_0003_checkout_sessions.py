"""Hosted checkout sessions for top-ups (T052).

Revision ID: s001_0003
Revises: s001_0002
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s001_0003"
down_revision = "s001_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE checkout_sessions (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      stripe_session_id text NOT NULL UNIQUE,
      amount_usd numeric(18,6) NOT NULL CHECK (amount_usd BETWEEN 5 AND 10000),
      status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'expired')),
      checkout_url text NOT NULL,
      expires_at timestamptz NOT NULL,
      idempotency_key text,
      txn_id text REFERENCES credit_transactions(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      completed_at timestamptz,
      CONSTRAINT uq_checkout_sessions_idempotency UNIQUE (workspace_id, idempotency_key)
    );
    CREATE INDEX ix_checkout_sessions_workspace ON checkout_sessions (workspace_id, created_at DESC);
    ALTER TABLE checkout_sessions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE checkout_sessions FORCE ROW LEVEL SECURITY;
    CREATE POLICY checkout_sessions_tenant ON checkout_sessions
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON checkout_sessions TO callwright_app;
    GRANT UPDATE (status, txn_id, completed_at) ON checkout_sessions TO callwright_app;

    -- Webhooks arrive without a workspace context; this returns only the owning workspace id.
    CREATE FUNCTION billing_checkout_workspace(p_stripe_session_id text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id FROM checkout_sessions WHERE stripe_session_id = p_stripe_session_id
    $$;
    REVOKE ALL ON FUNCTION billing_checkout_workspace(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION billing_checkout_workspace(text) TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
