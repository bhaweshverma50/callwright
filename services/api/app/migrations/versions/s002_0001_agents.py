"""Agents and immutable agent versions (002 T003, T020, T099).

* ``agents`` holds the mutable draft config; ``agent_versions`` the immutable snapshots.
* The two tables reference each other (``draft_version_id``, ``pinned_version_id``,
  ``agent_versions.agent_id``) through deferred foreign keys, so an agent and its version 1 are
  written in one transaction.
* Triggers: ``agents.type`` never changes (FR-002); ``agent_versions`` rows are never updated or
  deleted except by the table owner (maintenance); the draft and published versions always
  belong to the same agent (checked at commit).
* RLS on both tables; trigram index for name search (R21) and ``jsonb_path_ops`` indexes for the
  usage lookups of 005 and the ambient-audio guard.

Revision ID: s002_0001
Revises: s003_0001 (re-chained after 003 at the wave 2 merge)
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s002_0001"
down_revision = "s003_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""
    CREATE TABLE agents (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
      type text NOT NULL CHECK (type IN ('single_prompt', 'flow')),
      language text NOT NULL,
      draft_config jsonb NOT NULL,
      draft_revision integer NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
      draft_version_id text NOT NULL,
      pinned_version_id text,
      template_id text,
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz
    );

    CREATE TABLE agent_versions (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL,
      version_number integer NOT NULL CHECK (version_number >= 1),
      schema_version integer NOT NULL CHECK (schema_version >= 1),
      config jsonb NOT NULL,
      content_hash char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
      source text NOT NULL CHECK (source IN
        ('create', 'save', 'restore', 'template', 'duplicate', 'flow_publish', 'test')),
      restored_from_version_id text,
      parent_version_id text,
      summary jsonb NOT NULL,
      note text CHECK (note IS NULL OR char_length(note) <= 500),
      publish_blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
      created_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_agent_versions_agent_number UNIQUE (agent_id, version_number),
      CONSTRAINT restore_has_source CHECK ((source = 'restore') = (restored_from_version_id IS NOT NULL))
    );

    ALTER TABLE agents
      ADD CONSTRAINT fk_agents_draft_version FOREIGN KEY (draft_version_id)
        REFERENCES agent_versions(id) DEFERRABLE INITIALLY DEFERRED,
      ADD CONSTRAINT fk_agents_pinned_version FOREIGN KEY (pinned_version_id)
        REFERENCES agent_versions(id) DEFERRABLE INITIALLY DEFERRED;
    ALTER TABLE agent_versions
      ADD CONSTRAINT fk_agent_versions_agent FOREIGN KEY (agent_id)
        REFERENCES agents(id) DEFERRABLE INITIALLY DEFERRED,
      ADD CONSTRAINT fk_agent_versions_restored_from FOREIGN KEY (restored_from_version_id)
        REFERENCES agent_versions(id),
      ADD CONSTRAINT fk_agent_versions_parent FOREIGN KEY (parent_version_id)
        REFERENCES agent_versions(id);

    CREATE INDEX ix_agents_workspace_updated ON agents (workspace_id, updated_at DESC, id DESC)
      WHERE deleted_at IS NULL;
    CREATE INDEX ix_agents_name_trgm ON agents USING gin (name gin_trgm_ops);
    CREATE INDEX ix_agents_draft_config ON agents USING gin (draft_config jsonb_path_ops);
    CREATE INDEX ix_agents_pinned_version ON agents (pinned_version_id) WHERE pinned_version_id IS NOT NULL;
    CREATE INDEX ix_agent_versions_agent_number ON agent_versions (agent_id, version_number DESC);
    CREATE INDEX ix_agent_versions_agent_hash ON agent_versions (agent_id, content_hash);
    CREATE INDEX ix_agent_versions_config ON agent_versions USING gin (config jsonb_path_ops);
    """)

    # Triggers -------------------------------------------------------------------------------
    op.execute("""
    CREATE FUNCTION agents_type_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.type IS DISTINCT FROM OLD.type THEN
        RAISE EXCEPTION 'agents.type cannot change (FR-002)' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
        RAISE EXCEPTION 'agents.workspace_id cannot change' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER agents_type_immutable
      BEFORE UPDATE ON agents FOR EACH ROW EXECUTE FUNCTION agents_type_immutable();

    CREATE FUNCTION agent_versions_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF current_user <> (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = TG_RELID) THEN
        RAISE EXCEPTION 'agent_versions is immutable (% refused)', TG_OP
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER agent_versions_immutable
      BEFORE UPDATE OR DELETE ON agent_versions
      FOR EACH ROW EXECUTE FUNCTION agent_versions_immutable();

    CREATE FUNCTION agents_versions_same_agent() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM agent_versions v WHERE v.id = NEW.draft_version_id AND v.agent_id = NEW.id) THEN
        RAISE EXCEPTION 'draft version % does not belong to agent %', NEW.draft_version_id, NEW.id
          USING ERRCODE = 'foreign_key_violation';
      END IF;
      IF NEW.pinned_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM agent_versions v WHERE v.id = NEW.pinned_version_id AND v.agent_id = NEW.id
      ) THEN
        RAISE EXCEPTION 'published version % does not belong to agent %', NEW.pinned_version_id, NEW.id
          USING ERRCODE = 'foreign_key_violation';
      END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER agents_versions_same_agent
      AFTER INSERT OR UPDATE OF draft_version_id, pinned_version_id ON agents
      DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION agents_versions_same_agent();
    """)

    # RLS and grants --------------------------------------------------------------------------
    op.execute("""
    ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
    ALTER TABLE agents FORCE ROW LEVEL SECURITY;
    CREATE POLICY agents_tenant ON agents
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    ALTER TABLE agent_versions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE agent_versions FORCE ROW LEVEL SECURITY;
    CREATE POLICY agent_versions_tenant ON agent_versions
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON agents, agent_versions TO callwright_app;
    GRANT UPDATE (name, language, draft_config, draft_revision, draft_version_id, pinned_version_id,
                  updated_at, deleted_at)
      ON agents TO callwright_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
