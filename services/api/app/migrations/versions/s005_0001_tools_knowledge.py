"""Tools and knowledge (005 T006, T097, T100; data-model.md sections 1, 3, 4, 5).

* ``tools``: the workspace tool library. ``type`` never changes; a canned response
  (``mock_response``) exists only for ``http`` tools (FR-044).
* ``knowledge_bases``, ``kb_documents`` and ``kb_chunks`` with pgvector embeddings
  (``vector(1536)``) and an HNSW cosine index (m 16, ef_construction 64, research R14).
* Same content may not be uploaded twice into one knowledge base (unique ``(kb_id, sha256)``).
* RLS on every table, on ``app.workspace_id`` like every tenant table.

Revision ID: s005_0001
Revises: s003_0002 (the integrator re-chains it at the wave 3 merge)
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "s005_0001"
down_revision = "s003_0002"
branch_labels = None
depends_on = None

_TABLES = ("tools", "knowledge_bases", "kb_documents", "kb_chunks")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
    CREATE TABLE tools (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      type text NOT NULL CHECK (type IN ('end_call', 'transfer_call', 'press_digit', 'http')),
      name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{0,63}$'),
      description text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 1000),
      config jsonb NOT NULL,
      mock_response text CHECK (mock_response IS NULL OR char_length(mock_response) <= 16384),
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT mock_only_http CHECK (type = 'http' OR mock_response IS NULL)
    );
    CREATE INDEX ix_tools_workspace_type ON tools (workspace_id, type);
    CREATE INDEX ix_tools_workspace_name ON tools (workspace_id, lower(name));

    CREATE FUNCTION tools_type_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.type <> OLD.type THEN
        RAISE EXCEPTION 'tools.type cannot change';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tools_type_immutable BEFORE UPDATE ON tools
      FOR EACH ROW EXECUTE FUNCTION tools_type_immutable();

    CREATE TABLE knowledge_bases (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
      description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 500),
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX uq_knowledge_bases_workspace_name ON knowledge_bases (workspace_id, lower(name));

    CREATE TABLE kb_documents (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      kb_id text NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
      file_name text NOT NULL CHECK (char_length(file_name) BETWEEN 1 AND 255),
      display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 255),
      file_type text NOT NULL CHECK (file_type IN ('pdf', 'docx')),
      file_size bigint NOT NULL CHECK (file_size BETWEEN 1 AND 20971520),
      sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      storage_key text NOT NULL,
      status text NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
      error_code text CHECK (error_code IS NULL OR error_code IN (
        'no_extractable_text', 'corrupt_file', 'encrypted_file', 'embedding_unavailable',
        'too_many_chunks', 'internal')),
      error_message text,
      page_count integer,
      chunk_count integer,
      token_count integer,
      embedding_model text,
      attempts integer NOT NULL DEFAULT 0,
      replaces_doc_id text,
      uploaded_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      processing_started_at timestamptz,
      processed_at timestamptz,
      CONSTRAINT uq_kb_documents_kb_sha256 UNIQUE (kb_id, sha256)
    );
    CREATE INDEX ix_kb_documents_workspace_sha ON kb_documents (workspace_id, sha256);
    CREATE INDEX ix_kb_documents_kb_status ON kb_documents (kb_id, status);
    CREATE INDEX ix_kb_documents_kb_name ON kb_documents (kb_id, lower(file_name));

    CREATE TABLE kb_chunks (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      kb_id text NOT NULL,
      doc_id text NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
      ordinal integer NOT NULL CHECK (ordinal >= 0),
      content text NOT NULL,
      token_count integer NOT NULL,
      page_from integer,
      page_to integer,
      heading text,
      embedding vector(1536) NOT NULL,
      embedding_model text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_kb_chunks_embedding ON kb_chunks
      USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
    CREATE INDEX ix_kb_chunks_workspace_kb ON kb_chunks (workspace_id, kb_id);
    CREATE INDEX ix_kb_chunks_doc_ordinal ON kb_chunks (doc_id, ordinal);
    """)
    for table in _TABLES:
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON {table}
          USING (workspace_id = current_setting('app.workspace_id', true))
          WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO callwright_app;
        """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
