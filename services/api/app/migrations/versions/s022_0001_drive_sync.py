"""Google connections and Drive knowledge sync (022 T007; data-model.md).

* ``connections``: a Google account's access granted to a workspace. The refresh token lives in
  ``secrets`` (001) under ``secret_name``, never in this table.
* ``kb_sources``: a Drive folder or shared drive feeding one knowledge base through a connection.
* ``kb_source_files``: every Drive item a source has seen, with its change markers and the
  document serving it.
* ``kb_sync_runs``: one row per sync with its counts and per-file errors.
* ``connector_activity``: append-only who-did-what for connections and sources (FR-025).
* ``kb_documents`` gains the ``archived`` status, ``archived_at`` and ``source_id``. Search reads
  only ``ready`` documents, so archived ones leave search with no change to the call path.
* RLS on every new table; workspace-less crons use security-definer lookups returning ids only.

Revision ID: s022_0001
Revises: s002_0005
Create Date: 2026-11-12
"""

from __future__ import annotations

from alembic import op

revision = "s022_0001"
down_revision = "s002_0005"
branch_labels = None
depends_on = None

_TABLES = ("connections", "kb_sources", "kb_source_files", "kb_sync_runs", "connector_activity")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE connections (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      provider text NOT NULL CHECK (provider IN ('google')),
      kind text NOT NULL CHECK (kind IN ('oauth')),
      account_subject text NOT NULL,
      account_email text NOT NULL,
      scopes text[] NOT NULL DEFAULT '{}',
      sheets_access boolean NOT NULL DEFAULT false,
      secret_name text NOT NULL,
      health text NOT NULL DEFAULT 'healthy' CHECK (health IN ('healthy', 'failing', 'revoked')),
      health_reason text,
      last_success_at timestamptz,
      last_checked_at timestamptz,
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_connections_account UNIQUE (workspace_id, provider, account_subject)
    );

    CREATE TABLE kb_sources (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      kb_id text NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
      connection_id text NOT NULL REFERENCES connections(id) ON DELETE RESTRICT,
      kind text NOT NULL DEFAULT 'google_drive' CHECK (kind IN ('google_drive')),
      root_kind text NOT NULL CHECK (root_kind IN ('folder', 'shared_drive')),
      root_id text NOT NULL,
      drive_id text,
      root_name text NOT NULL,
      include_subfolders boolean NOT NULL DEFAULT true,
      interval_minutes int NOT NULL DEFAULT 15 CHECK (interval_minutes BETWEEN 5 AND 1440),
      state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'syncing', 'healthy', 'needs_attention')),
      attention_reason text
        CHECK (attention_reason IN (
          'access_lost', 'mass_archive', 'kb_full', 'no_credit', 'source_too_large'
        )),
      held_archive jsonb,
      last_success_at timestamptz,
      next_sync_at timestamptz,
      running_run_id text,
      running_since timestamptz,
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_kb_sources_root UNIQUE (kb_id, root_id)
    );
    CREATE INDEX ix_kb_sources_due ON kb_sources (next_sync_at) WHERE running_run_id IS NULL;
    CREATE INDEX ix_kb_sources_connection ON kb_sources (connection_id);

    CREATE TABLE kb_source_files (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      source_id text NOT NULL REFERENCES kb_sources(id) ON DELETE CASCADE,
      drive_file_id text NOT NULL,
      name text NOT NULL,
      path text NOT NULL DEFAULT '',
      mime_type text NOT NULL,
      web_view_link text,
      drive_version text,
      md5 text,
      size_bytes bigint,
      sha256 text,
      text_sha256 text,
      doc_id text REFERENCES kb_documents(id) ON DELETE SET NULL,
      pending_doc_id text,
      state text NOT NULL CHECK (state IN ('synced', 'skipped', 'failed', 'removed', 'kept')),
      reason text CHECK (reason IN (
        'unsupported_type', 'too_large', 'export_too_large', 'shortcut', 'duplicate', 'kb_full',
        'workspace_storage_full', 'download_failed', 'processing_failed'
      )),
      duplicate_of_doc_id text,
      message text,
      last_seen_run_id text,
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_kb_source_files_file UNIQUE (source_id, drive_file_id)
    );
    CREATE INDEX ix_kb_source_files_doc ON kb_source_files (doc_id);
    CREATE INDEX ix_kb_source_files_pending ON kb_source_files (pending_doc_id)
      WHERE pending_doc_id IS NOT NULL;

    CREATE TABLE kb_sync_runs (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      source_id text NOT NULL REFERENCES kb_sources(id) ON DELETE CASCADE,
      trigger text NOT NULL CHECK (trigger IN ('first', 'scheduled', 'manual', 'reconnect')),
      status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'held', 'failed')),
      failure_reason text CHECK (failure_reason IN (
        'access_lost', 'connection_revoked', 'google_unavailable', 'source_too_large', 'internal'
      )),
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      added int NOT NULL DEFAULT 0,
      updated int NOT NULL DEFAULT 0,
      unchanged int NOT NULL DEFAULT 0,
      renamed int NOT NULL DEFAULT 0,
      archived int NOT NULL DEFAULT 0,
      held_back int NOT NULL DEFAULT 0,
      skipped int NOT NULL DEFAULT 0,
      failed int NOT NULL DEFAULT 0,
      errors jsonb NOT NULL DEFAULT '[]',
      errors_truncated int NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_kb_sync_runs_source ON kb_sync_runs (source_id, started_at DESC);
    CREATE INDEX ix_kb_sync_runs_started ON kb_sync_runs (started_at);

    CREATE TABLE connector_activity (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      actor_user_id text,
      action text NOT NULL CHECK (action IN (
        'connection_added', 'connection_reconnected', 'connection_removed', 'source_added',
        'source_removed', 'held_archive_confirmed', 'held_archive_cancelled'
      )),
      subject_type text NOT NULL CHECK (subject_type IN ('connection', 'source')),
      subject_id text NOT NULL,
      detail jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_connector_activity_subject
      ON connector_activity (workspace_id, subject_id, created_at DESC);

    ALTER TABLE kb_documents DROP CONSTRAINT kb_documents_status_check;
    ALTER TABLE kb_documents ADD CONSTRAINT kb_documents_status_check
      CHECK (status IN ('uploaded', 'processing', 'ready', 'failed', 'archived'));
    ALTER TABLE kb_documents ADD COLUMN archived_at timestamptz;
    ALTER TABLE kb_documents ADD COLUMN source_id text REFERENCES kb_sources(id) ON DELETE SET NULL;
    CREATE INDEX ix_kb_documents_source ON kb_documents (source_id) WHERE source_id IS NOT NULL;
    CREATE INDEX ix_kb_documents_archived ON kb_documents (archived_at) WHERE status = 'archived';
    """)
    for table in _TABLES:
        grants = "SELECT, INSERT" if table == "connector_activity" else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON {table}
          USING (workspace_id = current_setting('app.workspace_id', true))
          WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
        GRANT {grants} ON {table} TO callwright_app;
        """)
    # Crons and jobs start without a request workspace: these return ids and workspace ids only.
    op.execute("""
    CREATE FUNCTION kb_sources_due(p_now timestamptz, p_limit int)
    RETURNS TABLE(id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT s.id, s.workspace_id FROM kb_sources s
      WHERE s.next_sync_at IS NOT NULL AND s.next_sync_at <= p_now
        AND (s.running_run_id IS NULL OR s.running_since < p_now - interval '30 minutes')
      ORDER BY s.next_sync_at
      LIMIT p_limit
    $$;

    CREATE FUNCTION kb_sources_workspace_for(p_source_id text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id FROM kb_sources WHERE id = p_source_id
    $$;

    CREATE FUNCTION kb_documents_archived_before(p_before timestamptz, p_limit int)
    RETURNS TABLE(id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT d.id, d.workspace_id FROM kb_documents d
      WHERE d.status = 'archived' AND d.archived_at < p_before
      ORDER BY d.archived_at
      LIMIT p_limit
    $$;

    CREATE FUNCTION kb_sync_runs_before(p_before timestamptz, p_limit int)
    RETURNS TABLE(id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT r.id, r.workspace_id FROM kb_sync_runs r
      WHERE r.started_at < p_before
      ORDER BY r.started_at
      LIMIT p_limit
    $$;
    """)
    for signature in (
        "kb_sources_due(timestamptz, int)",
        "kb_sources_workspace_for(text)",
        "kb_documents_archived_before(timestamptz, int)",
        "kb_sync_runs_before(timestamptz, int)",
    ):
        op.execute(f"""
        REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {signature} TO callwright_app;
        """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
