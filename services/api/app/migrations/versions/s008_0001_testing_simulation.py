"""Testing and simulation (008 T006, T090; data-model.md).

Tables: ``test_categories`` (with display colours), ``test_cases``, ``test_runs``,
``test_results``, ``simulation_experiments``, ``simulation_runs``, ``datasets`` and
``dataset_items``. Seed categories are written for every existing workspace here; new workspaces
get them on first use (``test_cases.service.ensure_seeds``).

``calls.origin`` and ``calls.simulation_run_id`` already exist (003); this adds the history index
on origin. ``calls.simulation_run_id`` gets no foreign key: the 006 dev seed writes simulated
calls without runs, and existing databases hold such rows. ``simulation_runs.output_call_id``
references ``calls``.

Internal endpoints (service token) find a run's workspace through the SECURITY DEFINER lookups
``test_runs_workspace_for`` and ``simulation_runs_workspace_for``, like ``calls_workspace_for``.

Tenancy: every table has FORCE RLS on ``app.workspace_id``.

Revision ID: s008_0001
Revises: s007_0001
Create Date: 2026-11-02
"""

from __future__ import annotations

from alembic import op

revision = "s008_0001"
down_revision = "s007_0001"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"

# Seed slug, name and palette colour (test_cases.service.SEED_CATEGORIES mirrors this).
SEEDS = (
    ("out_of_scope", "Out of scope", "#d97706"),
    ("bad_behaviour", "Bad behaviour", "#e11d48"),
    ("identity", "Identity", "#0284c7"),
    ("prompt_injection", "Prompt injection", "#7c3aed"),
    ("guardrails", "Guardrails", "#059669"),
)


def _rls(table: str) -> str:
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_tenant ON {table}
      USING (workspace_id = {WS})
      WITH CHECK (workspace_id = {WS});
    """


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE test_categories (
      workspace_id text NOT NULL REFERENCES workspaces(id),
      slug text NOT NULL CHECK (slug ~ '^[a-z][a-z0-9_]{{1,39}}$'),
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
      color text NOT NULL CHECK (color ~ '^#[0-9a-f]{{6}}$'),
      is_seed boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (workspace_id, slug)
    );
    CREATE UNIQUE INDEX uq_test_categories_name ON test_categories (workspace_id, lower(name));
    {_rls("test_categories")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON test_categories TO callwright_app;

    CREATE TABLE test_cases (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
      category_slug text NOT NULL,
      user_prompt text NOT NULL CHECK (char_length(user_prompt) BETWEEN 1 AND 2000),
      expected_behaviour text NOT NULL CHECK (char_length(expected_behaviour) BETWEEN 1 AND 2000),
      dynamic_variables jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      dedupe_key text NOT NULL,
      last_status text CHECK (last_status IN ('passed', 'failed', 'error')),
      last_run_id text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (workspace_id, category_slug) REFERENCES test_categories (workspace_id, slug)
    );
    CREATE UNIQUE INDEX uq_test_cases_dedupe ON test_cases (agent_id, dedupe_key);
    CREATE INDEX ix_test_cases_agent ON test_cases (workspace_id, agent_id, created_at);
    {_rls("test_cases")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON test_cases TO callwright_app;

    CREATE TABLE test_runs (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      number integer NOT NULL,
      target_type text NOT NULL CHECK (target_type IN ('draft', 'published', 'version')),
      agent_version_id text REFERENCES agent_versions(id),
      config_snapshot jsonb NOT NULL,
      config_hash text NOT NULL,
      agent_model text NOT NULL,
      judge_model text NOT NULL,
      status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
      total integer NOT NULL DEFAULT 0,
      passed integer NOT NULL DEFAULT 0,
      failed integer NOT NULL DEFAULT 0,
      errored integer NOT NULL DEFAULT 0,
      usage jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      cost_usd numeric(12, 6),
      error_message text,
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz,
      finished_at timestamptz,
      CHECK (passed + failed + errored <= total)
    );
    CREATE UNIQUE INDEX uq_test_runs_number ON test_runs (agent_id, number);
    CREATE INDEX ix_test_runs_agent ON test_runs (workspace_id, agent_id, created_at DESC);
    {_rls("test_runs")}
    GRANT SELECT, INSERT, UPDATE ON test_runs TO callwright_app;

    CREATE TABLE test_results (
      test_run_id text NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
      test_case_id text NOT NULL,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      position integer NOT NULL DEFAULT 0,
      case_name text NOT NULL,
      category_slug text NOT NULL,
      user_prompt text NOT NULL,
      expected_behaviour text NOT NULL,
      dynamic_variables jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'running', 'judging', 'done', 'cancelled')),
      agent_response text,
      tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
      nodes_visited text[] NOT NULL DEFAULT '{{}}',
      judge_status text CHECK (judge_status IN ('passed', 'failed', 'error')),
      judge_reasoning text,
      judge_model text,
      override_status text CHECK (override_status IN ('passed', 'failed')),
      override_note text CHECK (char_length(override_note) <= 500),
      overridden_at timestamptz,
      effective_status text GENERATED ALWAYS AS (coalesce(override_status, judge_status)) STORED,
      error_message text,
      duration_ms integer,
      usage jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      PRIMARY KEY (test_run_id, test_case_id)
    );
    CREATE INDEX ix_test_results_case ON test_results (workspace_id, test_case_id);
    {_rls("test_results")}
    GRANT SELECT, INSERT, UPDATE ON test_results TO callwright_app;

    CREATE TABLE simulation_experiments (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id),
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
      mode text NOT NULL CHECK (mode IN ('replay', 'persona')),
      target_type text NOT NULL CHECK (target_type IN ('published', 'draft', 'version', 'variant')),
      agent_version_id text REFERENCES agent_versions(id),
      variant_label text,
      config_snapshot jsonb NOT NULL,
      config_hash text NOT NULL,
      variant_diff jsonb,
      source text NOT NULL CHECK (source IN ('call_selection', 'dataset', 'issue_validation', 'api')),
      dataset_id text,
      issue_id text,
      settings jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
      total_count integer NOT NULL DEFAULT 0,
      completed_count integer NOT NULL DEFAULT 0,
      failed_count integer NOT NULL DEFAULT 0,
      cancelled_count integer NOT NULL DEFAULT 0,
      cost_usd numeric(12, 6),
      error_message text,
      hooks_fired_at timestamptz,
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz
    );
    CREATE INDEX ix_simulation_experiments_agent
      ON simulation_experiments (workspace_id, agent_id, created_at DESC);
    CREATE INDEX ix_simulation_experiments_recent ON simulation_experiments (workspace_id, created_at DESC);
    {_rls("simulation_experiments")}
    GRANT SELECT, INSERT, UPDATE ON simulation_experiments TO callwright_app;

    CREATE TABLE simulation_runs (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id),
      experiment_id text REFERENCES simulation_experiments(id) ON DELETE CASCADE,
      base_call_id text REFERENCES calls(id) ON DELETE SET NULL,
      mode text NOT NULL CHECK (mode IN ('replay', 'persona')),
      target_type text NOT NULL CHECK (target_type IN ('published', 'draft', 'version', 'variant')),
      agent_version_id text REFERENCES agent_versions(id),
      variant_label text,
      config_snapshot jsonb,
      config_hash text NOT NULL,
      persona_brief jsonb,
      persona_source text CHECK (persona_source IN ('extracted', 'provided')),
      dynamic_variables jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      settings jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
      output_call_id text,
      end_reason text CHECK (end_reason IN ('caller_turns_exhausted', 'caller_hung_up', 'agent_hangup',
                                            'call_transfer', 'turn_limit_reached', 'error')),
      diverged_at_turn integer,
      answer_source_counts jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      usage jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      cost_usd numeric(12, 6),
      error_message text,
      dispatched_at timestamptz,
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz,
      finished_at timestamptz,
      CHECK (experiment_id IS NOT NULL OR config_snapshot IS NOT NULL)
    );
    CREATE INDEX ix_simulation_runs_agent ON simulation_runs (workspace_id, agent_id, created_at DESC);
    CREATE INDEX ix_simulation_runs_experiment ON simulation_runs (experiment_id, created_at);
    CREATE INDEX ix_simulation_runs_base_call ON simulation_runs (base_call_id);
    CREATE INDEX ix_simulation_runs_status ON simulation_runs (workspace_id, status)
      WHERE status IN ('pending', 'running');
    {_rls("simulation_runs")}
    GRANT SELECT, INSERT, UPDATE ON simulation_runs TO callwright_app;

    ALTER TABLE simulation_runs ADD CONSTRAINT simulation_runs_output_call_fk
      FOREIGN KEY (output_call_id) REFERENCES calls(id) ON DELETE SET NULL
      DEFERRABLE INITIALLY DEFERRED;
    CREATE INDEX ix_calls_agent_origin_ended ON calls (workspace_id, agent_id, origin, ended_at DESC);

    CREATE TABLE datasets (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
      description text CHECK (char_length(description) <= 500),
      item_count integer NOT NULL DEFAULT 0 CHECK (item_count BETWEEN 0 AND 1000),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX uq_datasets_name ON datasets (workspace_id, lower(name));
    CREATE INDEX ix_datasets_recent ON datasets (workspace_id, updated_at DESC);
    {_rls("datasets")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON datasets TO callwright_app;

    CREATE TABLE dataset_items (
      dataset_id text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      added_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (dataset_id, call_id)
    );
    CREATE INDEX ix_dataset_items_added ON dataset_items (dataset_id, added_at DESC, call_id);
    CREATE INDEX ix_dataset_items_call ON dataset_items (call_id);
    {_rls("dataset_items")}
    GRANT SELECT, INSERT, DELETE ON dataset_items TO callwright_app;

    CREATE FUNCTION test_runs_workspace_for(p_id text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id FROM test_runs WHERE id = p_id
    $$;
    CREATE FUNCTION simulation_runs_workspace_for(p_id text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id FROM simulation_runs WHERE id = p_id
    $$;

    -- Runs whose runner went silent (sweeper cron): running without a heartbeat on the simulated
    -- call for p_stale_s, or dispatched but never started for p_lost_s.
    CREATE FUNCTION simulation_runs_stale(p_stale_s integer, p_lost_s integer)
    RETURNS TABLE (run_id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT r.id, r.workspace_id FROM simulation_runs r LEFT JOIN calls c ON c.id = r.output_call_id
      WHERE (r.status = 'running'
             AND coalesce(c.last_heartbeat_at, r.started_at) < now() - make_interval(secs => p_stale_s))
         OR (r.status = 'pending' AND r.dispatched_at < now() - make_interval(secs => p_lost_s))
      ORDER BY r.created_at
      LIMIT 500
    $$;

    -- Test cases a runner never answered (sweeper cron): unfinished results of runs started
    -- (or queued) more than p_s seconds ago.
    CREATE FUNCTION test_results_stale(p_s integer)
    RETURNS TABLE (test_run_id text, test_case_id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT r.test_run_id, r.test_case_id, r.workspace_id FROM test_results r
      JOIN test_runs t ON t.id = r.test_run_id
      WHERE t.status IN ('queued', 'running') AND r.state IN ('pending', 'running', 'judging')
        AND coalesce(t.started_at, t.created_at) < now() - make_interval(secs => p_s)
      ORDER BY t.created_at
      LIMIT 500
    $$;

    -- Retention (research R13): simulated transcripts and persona briefs follow the base call.
    CREATE FUNCTION simulation_data_purge()
    RETURNS bigint
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $$
      WITH gone AS (
        SELECT r.id, r.output_call_id FROM simulation_runs r LEFT JOIN calls b ON b.id = r.base_call_id
        WHERE r.base_call_id IS NOT NULL AND (b.id IS NULL OR b.transcript IS NULL)
          AND (r.persona_brief IS NOT NULL OR r.output_call_id IS NOT NULL)
      ), briefs AS (
        UPDATE simulation_runs SET persona_brief = NULL
        WHERE id IN (SELECT id FROM gone) AND persona_brief IS NOT NULL RETURNING id
      ), transcripts AS (
        UPDATE calls SET transcript = NULL, summary = NULL
        WHERE id IN (SELECT output_call_id FROM gone) AND transcript IS NOT NULL RETURNING id
      )
      SELECT (SELECT count(*) FROM briefs) + (SELECT count(*) FROM transcripts)
    $$;
    """)
    for fn in (
        "test_runs_workspace_for(text)",
        "simulation_runs_workspace_for(text)",
        "simulation_runs_stale(integer, integer)",
        "test_results_stale(integer)",
        "simulation_data_purge()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO callwright_app")
    values = ", ".join(f"('{slug}', '{name}', '{color}')" for slug, name, color in SEEDS)
    op.execute(f"""
    INSERT INTO test_categories (workspace_id, slug, name, color, is_seed)
    SELECT w.id, s.slug, s.name, s.color, true
      FROM workspaces w CROSS JOIN (VALUES {values}) AS s(slug, name, color)
    ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
