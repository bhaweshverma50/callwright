"""Local development identity provider store (schema local_idp).

Used only when AUTH_PROVIDER=local, so the sign-up, verification, sign-in, refresh and password
reset flows run offline. Production uses Supabase Auth and leaves these tables empty. They hold
IdP state (password hashes, one-time tokens, refresh sessions), not tenant data, so no RLS.

Revision ID: s001_0002
Revises: s001_0001
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s001_0002"
down_revision = "s001_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE SCHEMA local_idp;
    CREATE TABLE local_idp.users (
      id text PRIMARY KEY,
      email citext NOT NULL UNIQUE,
      password_hash text NOT NULL,
      email_confirmed_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE local_idp.one_time_tokens (
      token_hash text PRIMARY KEY,
      user_id text NOT NULL REFERENCES local_idp.users(id),
      kind text NOT NULL CHECK (kind IN ('verify_email', 'recovery')),
      expires_at timestamptz NOT NULL,
      used_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE local_idp.sessions (
      id text PRIMARY KEY,
      user_id text NOT NULL REFERENCES local_idp.users(id),
      refresh_token_hash text NOT NULL UNIQUE,
      created_at timestamptz NOT NULL DEFAULT now(),
      revoked_at timestamptz
    );
    CREATE INDEX ix_local_idp_sessions_user ON local_idp.sessions (user_id);
    GRANT USAGE ON SCHEMA local_idp TO callwright_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA local_idp TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
