"""Per-user preferences (013): the guided setup tour's progress.

* ``user_preferences``: one row per user, created on the first save. Today it holds the
  onboarding tour status (not_started, in_progress, skipped, completed) and the step the user
  is on. A user reads and writes only their own row in their own workspace (RLS on both
  ``app.user_id`` and ``app.workspace_id``).

Revision ID: s013_0001
Revises: s011_0001
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "s013_0001"
down_revision = "s011_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE user_preferences (
      user_id text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      workspace_id text NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      onboarding_status text NOT NULL DEFAULT 'not_started'
        CHECK (onboarding_status IN ('not_started', 'in_progress', 'skipped', 'completed')),
      onboarding_step text CHECK (onboarding_step ~ '^[a-z][a-z0-9_-]{0,39}$'),
      onboarding_updated_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_user_preferences_workspace ON user_preferences (workspace_id);

    ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
    ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY;
    CREATE POLICY user_preferences_self ON user_preferences
      USING (user_id = current_setting('app.user_id', true)
             AND workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (user_id = current_setting('app.user_id', true)
                  AND workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT, UPDATE ON user_preferences TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
