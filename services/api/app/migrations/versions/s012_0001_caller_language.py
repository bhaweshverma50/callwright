"""Caller language (012).

* ``caller_preferences``: the language a phone caller last switched to, per workspace and E.164
  number (the caller on inbound calls, the dialled number on outbound calls and callbacks).
* ``call_languages``: per call, the language it started in when that was the caller's saved
  language (``start``) and every switch the agent made (``switch``), for the call view.

Revision ID: s012_0001
Revises: s011_0001
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "s012_0001"
down_revision = "s011_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE caller_preferences (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      phone_number text NOT NULL CHECK (phone_number ~ '^\\+[1-9][0-9]{6,14}$'),
      preferred_language text NOT NULL CHECK (char_length(preferred_language) BETWEEN 2 AND 16),
      last_call_id text REFERENCES calls(id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_caller_preferences_number UNIQUE (workspace_id, phone_number)
    );
    CREATE INDEX ix_caller_preferences_updated ON caller_preferences (workspace_id, updated_at DESC);

    ALTER TABLE caller_preferences ENABLE ROW LEVEL SECURITY;
    ALTER TABLE caller_preferences FORCE ROW LEVEL SECURITY;
    CREATE POLICY caller_preferences_tenant ON caller_preferences
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON caller_preferences TO callwright_app;

    CREATE TABLE call_languages (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      kind text NOT NULL CHECK (kind IN ('start', 'switch')),
      language text NOT NULL CHECK (char_length(language) BETWEEN 2 AND 16),
      offset_ms integer CHECK (offset_ms >= 0),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_call_languages_call ON call_languages (call_id, created_at);
    CREATE UNIQUE INDEX uq_call_languages_start ON call_languages (call_id) WHERE kind = 'start';

    ALTER TABLE call_languages ENABLE ROW LEVEL SECURITY;
    ALTER TABLE call_languages FORCE ROW LEVEL SECURITY;
    CREATE POLICY call_languages_tenant ON call_languages
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON call_languages TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
