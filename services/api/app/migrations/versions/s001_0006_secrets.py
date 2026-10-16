"""Encrypted workspace secrets store (T088).

Revision ID: s001_0006
Revises: s001_0005
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s001_0006"
down_revision = "s001_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE secrets (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
      ciphertext bytea NOT NULL,
      wrapped_dek bytea NOT NULL,
      key_id text NOT NULL,
      masked text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_secrets_workspace_name UNIQUE (workspace_id, name)
    );
    ALTER TABLE secrets ENABLE ROW LEVEL SECURITY;
    ALTER TABLE secrets FORCE ROW LEVEL SECURITY;
    CREATE POLICY secrets_tenant ON secrets
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON secrets TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
