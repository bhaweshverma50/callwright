"""Background (ambient) audio uploads (002 T036, research R19).

Revision ID: s002_0003
Revises: s002_0002
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s002_0003"
down_revision = "s002_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ambient_audio_files (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      storage_key text NOT NULL UNIQUE,
      filename text NOT NULL CHECK (char_length(filename) BETWEEN 1 AND 200),
      content_type text NOT NULL CHECK (content_type IN
        ('audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/flac', 'audio/aac', 'audio/opus')),
      size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz,
      CONSTRAINT storage_key_in_workspace CHECK (storage_key LIKE 'workspaces/' || workspace_id || '/ambient/%')
    );
    CREATE INDEX ix_ambient_audio_workspace ON ambient_audio_files (workspace_id, created_at DESC)
      WHERE deleted_at IS NULL;
    ALTER TABLE ambient_audio_files ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ambient_audio_files FORCE ROW LEVEL SECURITY;
    CREATE POLICY ambient_audio_files_tenant ON ambient_audio_files
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON ambient_audio_files TO callwright_app;
    GRANT UPDATE (deleted_at) ON ambient_audio_files TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
