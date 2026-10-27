"""Quality and evaluations (007 T003, T074; data-model.md).

Tables: ``analysis_variables``, ``call_analyses``, ``evaluators``, ``evaluator_versions``,
``agent_eval_settings``, ``evaluator_run_groups``, ``evaluator_runs``, ``evaluator_result_items``,
``annotations`` and ``call_embeddings``; the real ``analytics.evaluator_verdicts_v``.

Tenancy: every table has FORCE RLS on ``app.workspace_id``. ``evaluators`` and
``evaluator_versions`` also hold the built-in catalog with ``workspace_id IS NULL``: the app role
may read those rows but only write its own workspace's rows; the admin role (the registry's
startup sync) writes only built-in rows.

The verdicts view keeps the 006 stub's columns (``CREATE OR REPLACE`` keeps the grant) and, like
the other analytics views, runs with the owner's rights and filters on ``app.workspace_id``
itself. It counts current completed pass or fail runs of live calls.

Revision ID: s007_0001
Revises: s006_0002
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op

revision = "s007_0001"
down_revision = "s006_0002"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"
EMBEDDING_DIMENSIONS = 1536  # 005's embedding dimension (app/knowledge/embeddings/base.py)


def _rls(table: str) -> str:
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_tenant ON {table}
      USING (workspace_id = {WS})
      WITH CHECK (workspace_id = {WS});
    """


def _catalog_rls(table: str) -> str:
    """Built-in rows (workspace_id IS NULL) readable by every workspace, written by admin only."""
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_read ON {table} FOR SELECT
      USING (workspace_id = {WS} OR workspace_id IS NULL);
    CREATE POLICY {table}_insert ON {table} FOR INSERT
      WITH CHECK (workspace_id = {WS});
    CREATE POLICY {table}_update ON {table} FOR UPDATE
      USING (workspace_id = {WS}) WITH CHECK (workspace_id = {WS});
    CREATE POLICY {table}_builtin ON {table} TO callwright_admin
      USING (workspace_id IS NULL) WITH CHECK (workspace_id IS NULL);
    GRANT SELECT, INSERT, UPDATE ON {table} TO callwright_app, callwright_admin;
    """


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE analysis_variables (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{{0,63}}$'),
      type text NOT NULL CHECK (type IN ('boolean', 'string', 'number', 'choice')),
      description text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 500),
      choices text[],
      position integer NOT NULL DEFAULT 0,
      deleted_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((type = 'choice') = (choices IS NOT NULL))
    );
    CREATE UNIQUE INDEX uq_analysis_variables_agent_name
      ON analysis_variables (agent_id, name) WHERE deleted_at IS NULL;
    CREATE INDEX ix_analysis_variables_agent ON analysis_variables (workspace_id, agent_id, position);
    {_rls("analysis_variables")}
    GRANT SELECT, INSERT, UPDATE ON analysis_variables TO callwright_app;

    CREATE TABLE call_analyses (
      call_id text PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'skipped', 'error')),
      skip_reason text CHECK (skip_reason IN ('insufficient_credit')),
      error text,
      model text,
      variable_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
      summary text CHECK (char_length(summary) <= 600),
      sentiment text CHECK (sentiment IN ('positive', 'neutral', 'negative', 'unknown')),
      "values" jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      input_tokens integer NOT NULL DEFAULT 0,
      output_tokens integer NOT NULL DEFAULT 0,
      raw_cost_usd numeric(12,6) NOT NULL DEFAULT 0,
      charge_txn_id text,
      attempt integer NOT NULL DEFAULT 1,
      analyzed_at timestamptz,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    {_rls("call_analyses")}
    GRANT SELECT, INSERT, UPDATE ON call_analyses TO callwright_app;
    """)

    op.execute(f"""
    CREATE TABLE evaluators (
      id text PRIMARY KEY,
      workspace_id text REFERENCES workspaces(id),
      kind text NOT NULL CHECK (kind IN ('builtin', 'custom')),
      evaluator_type text NOT NULL,
      name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{{0,63}}$'),
      display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 80),
      description text CHECK (char_length(description) <= 500),
      scope text NOT NULL CHECK (scope IN ('call', 'turn', 'flow_node')),
      cost_class text NOT NULL CHECK (cost_class IN ('free', 'llm_judge')),
      output_kind text NOT NULL DEFAULT 'class'
        CHECK (output_kind IN ('class', 'anomaly', 'audio_quality', 'process_reward')),
      agent_types text[] NOT NULL,
      settings_schema jsonb NOT NULL DEFAULT '{{"fields": []}}'::jsonb,
      score_range jsonb NOT NULL DEFAULT '{{"min": 0, "max": 1}}'::jsonb,
      current_version integer NOT NULL DEFAULT 1 CHECK (current_version >= 1),
      enabled_by_default boolean NOT NULL DEFAULT false,
      created_by text,
      deleted_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((kind = 'builtin') = (workspace_id IS NULL))
    );
    CREATE UNIQUE INDEX uq_evaluators_builtin_name ON evaluators (name) WHERE workspace_id IS NULL;
    CREATE UNIQUE INDEX uq_evaluators_custom_name
      ON evaluators (workspace_id, name) WHERE workspace_id IS NOT NULL AND deleted_at IS NULL;
    {_catalog_rls("evaluators")}

    CREATE TABLE evaluator_versions (
      evaluator_id text NOT NULL REFERENCES evaluators(id),
      version integer NOT NULL CHECK (version >= 1),
      workspace_id text REFERENCES workspaces(id),
      definition jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      judge_model text,
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (evaluator_id, version)
    );
    {_catalog_rls("evaluator_versions")}

    CREATE TABLE agent_eval_settings (
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      evaluator_id text NOT NULL REFERENCES evaluators(id),
      enabled boolean NOT NULL,
      overrides jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      is_headline boolean NOT NULL DEFAULT false,
      headline_position smallint CHECK (headline_position BETWEEN 1 AND 4),
      updated_by text,
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (agent_id, evaluator_id),
      CHECK (is_headline = (headline_position IS NOT NULL))
    );
    CREATE UNIQUE INDEX uq_agent_eval_settings_headline
      ON agent_eval_settings (agent_id, headline_position) WHERE is_headline;
    {_rls("agent_eval_settings")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON agent_eval_settings TO callwright_app;
    """)

    op.execute(f"""
    CREATE TABLE evaluator_run_groups (
      run_group_id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      trigger text NOT NULL CHECK (trigger IN ('pipeline', 'rerun', 'dataset', 'simulation')),
      idempotency_key text NOT NULL,
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done')),
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      CONSTRAINT uq_evaluator_run_groups_key UNIQUE (call_id, idempotency_key)
    );
    -- "Checks are already running": one active group per call (research R5).
    CREATE UNIQUE INDEX uq_evaluator_run_groups_active
      ON evaluator_run_groups (call_id) WHERE status = 'active';
    {_rls("evaluator_run_groups")}
    GRANT SELECT, INSERT, UPDATE ON evaluator_run_groups TO callwright_app;

    CREATE TABLE evaluator_runs (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      agent_id text NOT NULL,
      evaluator_id text NOT NULL,
      evaluator_version integer NOT NULL,
      run_group_id text NOT NULL REFERENCES evaluator_run_groups(run_group_id) ON DELETE CASCADE,
      trigger text NOT NULL CHECK (trigger IN ('pipeline', 'rerun', 'dataset', 'simulation')),
      settings_snapshot jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      settings_hash text NOT NULL,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'skipped', 'error')),
      skip_reason text CHECK (skip_reason IN
        ('insufficient_credit', 'not_applicable_agent_type', 'evaluator_disabled', 'not_sampled')),
      error text,
      verdict text CHECK (verdict IN ('pass', 'fail', 'not_applicable')),
      score double precision,
      rationale text,
      judge_model text,
      input_tokens integer NOT NULL DEFAULT 0,
      output_tokens integer NOT NULL DEFAULT 0,
      raw_cost_usd numeric(12,6) NOT NULL DEFAULT 0,
      charge_txn_id text,
      attempt smallint NOT NULL DEFAULT 1,
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz,
      completed_at timestamptz,
      superseded_at timestamptz,
      FOREIGN KEY (evaluator_id, evaluator_version) REFERENCES evaluator_versions (evaluator_id, version),
      CHECK (status <> 'completed' OR verdict IS NOT NULL),
      CHECK (verdict IS NULL OR verdict = 'not_applicable' OR char_length(coalesce(rationale, '')) > 0)
    );
    CREATE INDEX ix_evaluator_runs_current ON evaluator_runs (workspace_id, call_id)
      WHERE superseded_at IS NULL;
    CREATE INDEX ix_evaluator_runs_evaluator ON evaluator_runs (workspace_id, evaluator_id, completed_at);
    CREATE INDEX ix_evaluator_runs_agent ON evaluator_runs (workspace_id, agent_id, completed_at);
    CREATE INDEX ix_evaluator_runs_group ON evaluator_runs (run_group_id);
    {_rls("evaluator_runs")}
    GRANT SELECT, INSERT, UPDATE ON evaluator_runs TO callwright_app;

    CREATE TABLE evaluator_result_items (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      run_id text NOT NULL REFERENCES evaluator_runs(id) ON DELETE CASCADE,
      position integer NOT NULL DEFAULT 0,
      turn_index integer,
      flow_node_id text,
      flow_node_label text,
      start_ms integer,
      duration_ms integer,
      verdict text NOT NULL CHECK (verdict IN ('pass', 'fail', 'not_applicable')),
      score double precision,
      rationale text NOT NULL DEFAULT '',
      evidence jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      CHECK (verdict = 'not_applicable' OR char_length(rationale) > 0)
    );
    CREATE INDEX ix_evaluator_result_items_run ON evaluator_result_items (run_id, position);
    {_rls("evaluator_result_items")}
    GRANT SELECT, INSERT ON evaluator_result_items TO callwright_app;

    CREATE TABLE annotations (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      user_id text NOT NULL,
      user_display_name text NOT NULL DEFAULT '',
      label text NOT NULL CHECK (label IN ('good', 'bad')),
      note text CHECK (char_length(note) <= 2000),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_annotations_call_user UNIQUE (call_id, user_id)
    );
    CREATE INDEX ix_annotations_ws_call ON annotations (workspace_id, call_id);
    CREATE INDEX ix_annotations_ws_user ON annotations (workspace_id, user_id);
    {_rls("annotations")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON annotations TO callwright_app;

    CREATE TABLE call_embeddings (
      call_id text PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL,
      ended_at timestamptz NOT NULL,
      embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL,
      model text NOT NULL,
      source_sha256 text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_call_embeddings_hnsw ON call_embeddings
      USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
    CREATE INDEX ix_call_embeddings_agent ON call_embeddings (workspace_id, agent_id, ended_at);
    {_rls("call_embeddings")}
    GRANT SELECT, INSERT, UPDATE ON call_embeddings TO callwright_app;
    """)

    op.execute(f"""
    CREATE OR REPLACE VIEW analytics.evaluator_verdicts_v WITH (security_barrier = true) AS
      SELECT r.workspace_id::text AS workspace_id, r.call_id::text AS call_id,
             r.agent_id::text AS agent_id, e.name::text AS evaluator_name,
             r.verdict::text AS verdict, r.score::numeric AS score,
             c.created_at::timestamptz AS started_at
        FROM public.evaluator_runs r
        JOIN public.evaluators e ON e.id = r.evaluator_id
        JOIN public.calls c ON c.id = r.call_id
       WHERE r.superseded_at IS NULL AND r.status = 'completed' AND r.verdict IN ('pass', 'fail')
         AND c.origin = 'live' AND r.workspace_id = {WS};
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
