"""Issues and auto-fix (009 T006; data-model.md).

Tables: ``issues``, ``issue_samples``, ``issue_failure_embeddings``, ``issue_fixes``,
``issue_validations`` and ``issue_detection_runs``. Enumerations are text columns with CHECK
constraints, like the rest of the schema.

* One running detection per agent (partial unique index) and one running validation per issue.
* ``issue_validations`` rows are evidence: once ``status`` leaves ``running`` a trigger refuses
  every further update, and the app role cannot delete them.
* Samples and cached failure embeddings follow their call and evaluator run (``ON DELETE
  CASCADE``), so retention purges them; validation evidence keeps only ids and counts.
* Crons find work across workspaces through SECURITY DEFINER functions:
  ``issue_validations_running`` (finalize sweeper), ``issue_detection_runs_stale`` (detections
  whose worker died) and ``issues_applied_audit`` (SC-001 nightly audit).

Tenancy: every table has FORCE RLS on ``app.workspace_id``.

Revision ID: s009_0001
Revises: s008_0001
Create Date: 2026-11-02
"""

from __future__ import annotations

from alembic import op

revision = "s009_0001"
down_revision = "s007_0002"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"
DIMENSIONS = 1536  # 005's embedding dimension (app.llms.embeddings.base.DIMENSIONS)


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
    CREATE TABLE issues (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      agent_type text NOT NULL CHECK (agent_type IN ('single_prompt', 'flow')),
      title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 80),
      description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 1000),
      suspected_cause text CHECK (char_length(suspected_cause) <= 1000),
      evaluator_id text NOT NULL,
      evaluator_name text NOT NULL,
      evaluator_display_name text NOT NULL,
      evaluator_version integer NOT NULL,
      flow_node_id text,
      flow_node_label text,
      status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'validating', 'validated', 'applied', 'dismissed')),
      origin text NOT NULL DEFAULT 'real' CHECK (origin IN ('real', 'simulated', 'mixed')),
      affected_call_count integer NOT NULL DEFAULT 0 CHECK (affected_call_count >= 0),
      current_version_call_count integer NOT NULL DEFAULT 0 CHECK (current_version_call_count >= 0),
      first_seen_at timestamptz NOT NULL,
      last_seen_at timestamptz NOT NULL,
      centroid vector({DIMENSIONS}),
      window_days integer NOT NULL DEFAULT 14 CHECK (window_days IN (7, 14, 30, 90)),
      current_fix_revision integer,
      calibration_warning boolean NOT NULL DEFAULT false,
      recurrence_of text REFERENCES issues(id),
      applied_agent_version_id text REFERENCES agent_versions(id),
      applied_fix_revision integer,
      applied_tool_copies jsonb NOT NULL DEFAULT '[]'::jsonb,
      applied_at timestamptz,
      applied_by text,
      dismiss_reason text
        CHECK (dismiss_reason IN ('not_a_problem', 'evaluator_wrong', 'wont_fix', 'duplicate', 'other')),
      dismiss_note text CHECK (char_length(dismiss_note) <= 500),
      duplicate_of text REFERENCES issues(id),
      dismissed_at timestamptz,
      dismissed_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK (dismiss_reason IS DISTINCT FROM 'other' OR char_length(coalesce(dismiss_note, '')) > 0),
      CHECK (dismiss_reason IS DISTINCT FROM 'duplicate' OR duplicate_of IS NOT NULL),
      CHECK (status <> 'applied' OR applied_agent_version_id IS NOT NULL),
      CHECK (status <> 'dismissed' OR dismiss_reason IS NOT NULL)
    );
    CREATE INDEX ix_issues_agent_last_seen ON issues (workspace_id, agent_id, last_seen_at DESC);
    CREATE INDEX ix_issues_recent ON issues (workspace_id, last_seen_at DESC);
    CREATE INDEX ix_issues_applied_version ON issues (workspace_id, applied_agent_version_id)
      WHERE applied_agent_version_id IS NOT NULL;
    CREATE INDEX ix_issues_match ON issues (agent_id, evaluator_id, flow_node_id);
    {_rls("issues")}
    GRANT SELECT, INSERT, UPDATE ON issues TO callwright_app;

    CREATE TABLE issue_samples (
      issue_id text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      evaluator_result_ids text[] NOT NULL DEFAULT '{{}}',
      reason_excerpt text NOT NULL DEFAULT '' CHECK (char_length(reason_excerpt) <= 500),
      agent_version_id text,
      call_origin text NOT NULL CHECK (call_origin IN ('live', 'simulation')),
      base_call_id text,
      failed_at timestamptz NOT NULL,
      PRIMARY KEY (issue_id, call_id)
    );
    CREATE INDEX ix_issue_samples_recent ON issue_samples (issue_id, failed_at DESC);
    CREATE INDEX ix_issue_samples_call ON issue_samples (call_id);
    {_rls("issue_samples")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON issue_samples TO callwright_app;

    CREATE TABLE issue_failure_embeddings (
      evaluator_result_id text NOT NULL REFERENCES evaluator_runs(id) ON DELETE CASCADE,
      node_key text NOT NULL DEFAULT '',
      workspace_id text NOT NULL REFERENCES workspaces(id),
      embedding_model text NOT NULL,
      source_sha256 text NOT NULL,
      embedding vector({DIMENSIONS}) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (evaluator_result_id, node_key)
    );
    {_rls("issue_failure_embeddings")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON issue_failure_embeddings TO callwright_app;

    CREATE TABLE issue_fixes (
      issue_id text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
      revision integer NOT NULL CHECK (revision >= 1),
      workspace_id text NOT NULL REFERENCES workspaces(id),
      kind text NOT NULL CHECK (kind IN ('prompt_edit', 'node_prompt_edit', 'add_guardrail',
        'tool_description_edit', 'transition_condition_edit', 'add_transition', 'node_tool_attachment',
        'kb_attach')),
      payload jsonb NOT NULL,
      rationale text NOT NULL DEFAULT '' CHECK (char_length(rationale) <= 4000),
      source text NOT NULL CHECK (source IN ('ai', 'manual')),
      guidance text CHECK (char_length(guidance) <= 1000),
      base_agent_version_id text NOT NULL REFERENCES agent_versions(id),
      base_config_hash text NOT NULL,
      variant_config_hash text,
      variant_snapshot jsonb,
      diff jsonb NOT NULL DEFAULT '[]'::jsonb,
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'validating', 'passed', 'failed',
        'inconclusive', 'superseded', 'applied', 'advisory')),
      cost_usd numeric(12, 6),
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (issue_id, revision),
      CHECK (status = 'advisory' OR variant_config_hash IS NOT NULL)
    );
    {_rls("issue_fixes")}
    GRANT SELECT, INSERT, UPDATE ON issue_fixes TO callwright_app;

    CREATE TABLE issue_validations (
      issue_id text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
      attempt integer NOT NULL CHECK (attempt >= 1),
      workspace_id text NOT NULL REFERENCES workspaces(id),
      fix_revision integer NOT NULL,
      auto boolean NOT NULL DEFAULT false,
      mode text NOT NULL CHECK (mode IN ('persona', 'replay')),
      min_improvement_pp numeric(5, 2) NOT NULL CHECK (min_improvement_pp BETWEEN 5 AND 50),
      max_regression_pp numeric(5, 2) NOT NULL CHECK (max_regression_pp BETWEEN 0 AND 20),
      min_sample integer NOT NULL CHECK (min_sample BETWEEN 3 AND 50),
      base_agent_version_id text NOT NULL REFERENCES agent_versions(id),
      base_config_hash text NOT NULL,
      variant_config_hash text NOT NULL,
      affected_call_ids text[] NOT NULL,
      guard_call_ids text[] NOT NULL DEFAULT '{{}}',
      control_experiment_id text NOT NULL REFERENCES simulation_experiments(id),
      treatment_experiment_id text NOT NULL REFERENCES simulation_experiments(id),
      status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'cancelled', 'error')),
      decision text CHECK (decision IN ('passed', 'failed', 'inconclusive')),
      reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
      headline jsonb,
      evaluator_results jsonb NOT NULL DEFAULT '[]'::jsonb,
      treatment_runs_total integer NOT NULL DEFAULT 0,
      treatment_runs_failed integer NOT NULL DEFAULT 0,
      estimated_cost_usd numeric(12, 6),
      cost_usd numeric(12, 6),
      error_message text,
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      PRIMARY KEY (issue_id, attempt),
      FOREIGN KEY (issue_id, fix_revision) REFERENCES issue_fixes (issue_id, revision),
      CHECK (status <> 'completed' OR decision IS NOT NULL)
    );
    CREATE UNIQUE INDEX uq_issue_validations_running ON issue_validations (issue_id)
      WHERE status = 'running';
    CREATE INDEX ix_issue_validations_control ON issue_validations (control_experiment_id);
    CREATE INDEX ix_issue_validations_treatment ON issue_validations (treatment_experiment_id);
    {_rls("issue_validations")}
    GRANT SELECT, INSERT, UPDATE ON issue_validations TO callwright_app;

    -- Evidence is written once: a finished attempt can never change again.
    CREATE FUNCTION issue_validations_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'issue_validations: attempt % of % is final and cannot change',
          OLD.attempt, OLD.issue_id USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END
    $$;
    CREATE TRIGGER issue_validations_final BEFORE UPDATE ON issue_validations
      FOR EACH ROW EXECUTE FUNCTION issue_validations_immutable();

    CREATE TABLE issue_detection_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      window_days integer NOT NULL CHECK (window_days IN (7, 14, 30, 90)),
      include_simulated boolean NOT NULL DEFAULT false,
      status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
      window_start timestamptz NOT NULL,
      window_end timestamptz NOT NULL,
      calls_scanned integer NOT NULL DEFAULT 0,
      failures_scanned integer NOT NULL DEFAULT 0,
      issues_created integer NOT NULL DEFAULT 0,
      issues_updated integer NOT NULL DEFAULT 0,
      cost_usd numeric(12, 6),
      error_message text,
      created_by text,
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz
    );
    CREATE UNIQUE INDEX uq_issue_detection_running ON issue_detection_runs (agent_id)
      WHERE status = 'running';
    CREATE INDEX ix_issue_detection_agent ON issue_detection_runs (workspace_id, agent_id, started_at DESC);
    {_rls("issue_detection_runs")}
    GRANT SELECT, INSERT, UPDATE ON issue_detection_runs TO callwright_app;

    -- Running validations whose batches have both finished (finalize sweeper cron).
    CREATE FUNCTION issue_validations_running()
    RETURNS TABLE (workspace_id text, issue_id text, attempt integer)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT v.workspace_id, v.issue_id, v.attempt FROM issue_validations v
      JOIN simulation_experiments c ON c.id = v.control_experiment_id
      JOIN simulation_experiments t ON t.id = v.treatment_experiment_id
      WHERE v.status = 'running'
        AND c.status IN ('completed', 'failed', 'cancelled')
        AND t.status IN ('completed', 'failed', 'cancelled')
      ORDER BY v.started_at
      LIMIT 200
    $$;

    -- Detections whose worker died: running for longer than p_s seconds.
    CREATE FUNCTION issue_detection_runs_stale(p_s integer)
    RETURNS TABLE (id uuid, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT d.id, d.workspace_id FROM issue_detection_runs d
      WHERE d.status = 'running' AND d.started_at < now() - make_interval(secs => p_s)
      ORDER BY d.started_at
      LIMIT 200
    $$;

    -- SC-001: every applied issue, its applied version's content and the passing attempt of the
    -- applied revision (null when there is none).
    CREATE FUNCTION issues_applied_audit()
    RETURNS TABLE (issue_id text, workspace_id text, agent_version_id text, version_config jsonb,
                   version_hash text, tool_copies jsonb, passing_variant_hash text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT i.id, i.workspace_id, i.applied_agent_version_id, v.config, v.content_hash,
             i.applied_tool_copies,
             (SELECT a.variant_config_hash FROM issue_validations a
               WHERE a.issue_id = i.id AND a.fix_revision = i.applied_fix_revision
                 AND a.status = 'completed' AND a.decision = 'passed'
               ORDER BY a.attempt DESC LIMIT 1)
        FROM issues i JOIN agent_versions v ON v.id = i.applied_agent_version_id
       WHERE i.status = 'applied'
       ORDER BY i.applied_at
    $$;
    """)
    for fn in (
        "issue_validations_running()",
        "issue_detection_runs_stale(integer)",
        "issues_applied_audit()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO callwright_app")


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
