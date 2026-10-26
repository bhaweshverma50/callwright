"""Calls and analytics read side (006 T004, T089): list indexes, assistant and copilot audit
tables, the ``analytics`` schema with its read-only views and the ``cw_analytics_reader`` role.

``started_at`` in the 006 contracts is ``calls.created_at`` (when the call was placed); the
existing ``ix_calls_workspace_created`` already serves the default order.

The ``analytics`` views are the only relations the assistant's executor can read (research R4).
They run with the view owner's rights so ``cw_analytics_reader`` needs no grant on ``calls`` or
``call_events``; every view therefore filters on ``app.workspace_id`` itself, so tenancy holds
even when the owner bypasses RLS (a superuser in local Postgres). Base tables keep FORCE RLS.

Revision ID: s006_0001
Revises: s003_0002
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "s006_0001"
down_revision = "s005_0001"
branch_labels = None
depends_on = None

WS = "current_setting('app.workspace_id', true)"


def _rls(table: str) -> str:
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_tenant ON {table}
      USING (workspace_id = {WS})
      WITH CHECK (workspace_id = {WS});
    """


def upgrade() -> None:
    # Call list sort and filter indexes (data-model section 2) ---------------------------------
    op.execute(r"""
    CREATE INDEX ix_calls_ws_agent_created ON calls (workspace_id, agent_id, created_at DESC);
    CREATE INDEX ix_calls_ws_status_created ON calls (workspace_id, status, created_at DESC);
    CREATE INDEX ix_calls_ws_origin_created ON calls (workspace_id, origin, created_at DESC);
    CREATE INDEX ix_calls_ws_duration ON calls (workspace_id, billable_seconds);
    CREATE INDEX ix_calls_ws_cost ON calls (workspace_id, cost_total_usd);
    CREATE INDEX ix_calls_ws_latency ON calls (workspace_id, ((latency_stats->>'e2e_avg_ms')::integer));
    CREATE INDEX ix_calls_ws_from_digits
      ON calls (workspace_id, regexp_replace(from_number, '\D', '', 'g') text_pattern_ops);
    CREATE INDEX ix_calls_ws_to_digits
      ON calls (workspace_id, regexp_replace(to_number, '\D', '', 'g') text_pattern_ops);
    CREATE INDEX ix_calls_id_prefix ON calls (workspace_id, id text_pattern_ops);
    """)

    # Audit tables -------------------------------------------------------------------------------
    op.execute(f"""
    CREATE TABLE analytics_chat_requests (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      user_id text NOT NULL,
      idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 255),
      question text NOT NULL CHECK (char_length(question) <= 2000),
      metric_queries jsonb NOT NULL DEFAULT '[]'::jsonb,
      outcome text NOT NULL CHECK (outcome IN ('answered', 'declined', 'failed', 'refused_balance')),
      response jsonb,
      input_tokens integer NOT NULL DEFAULT 0,
      output_tokens integer NOT NULL DEFAULT 0,
      raw_cost_usd numeric(12,6) NOT NULL DEFAULT 0,
      charge_txn_id text,
      latency_ms integer NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_analytics_chat_requests_key UNIQUE (workspace_id, idempotency_key)
    );
    CREATE INDEX ix_analytics_chat_requests_created ON analytics_chat_requests (created_at);
    {_rls("analytics_chat_requests")}
    GRANT SELECT, INSERT, UPDATE ON analytics_chat_requests TO callwright_app;

    CREATE TABLE voice_command_logs (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      user_id text NOT NULL,
      route text NOT NULL CHECK (char_length(route) <= 300),
      transcript text NOT NULL CHECK (char_length(transcript) <= 1000),
      action text NOT NULL
        CHECK (action IN ('navigate', 'route_to_copilot', 'ui_action', 'answer', 'decline')),
      downgraded boolean NOT NULL DEFAULT false,
      stt_seconds numeric(8,2) NOT NULL DEFAULT 0,
      raw_cost_usd numeric(12,6) NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_voice_command_logs_created ON voice_command_logs (created_at);
    {_rls("voice_command_logs")}
    GRANT SELECT, INSERT ON voice_command_logs TO callwright_app;

    CREATE FUNCTION analytics_audit_purge(p_days integer)
    RETURNS bigint
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $$
      WITH a AS (
        DELETE FROM analytics_chat_requests WHERE created_at < now() - make_interval(days => p_days)
        RETURNING 1
      ), v AS (
        DELETE FROM voice_command_logs WHERE created_at < now() - make_interval(days => p_days)
        RETURNING 1
      )
      SELECT (SELECT count(*) FROM a) + (SELECT count(*) FROM v)
    $$;
    REVOKE ALL ON FUNCTION analytics_audit_purge(integer) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION analytics_audit_purge(integer) TO callwright_app;
    """)

    # analytics schema, reader role and views (research R4) -------------------------------------
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cw_analytics_reader') THEN
        CREATE ROLE cw_analytics_reader NOLOGIN NOBYPASSRLS;
      END IF;
    END $$;
    GRANT cw_analytics_reader TO callwright_app;
    CREATE SCHEMA IF NOT EXISTS analytics;
    REVOKE ALL ON SCHEMA analytics FROM PUBLIC;
    GRANT USAGE ON SCHEMA analytics TO cw_analytics_reader;
    """)
    op.execute(f"""
    CREATE OR REPLACE VIEW analytics.calls_v WITH (security_barrier = true) AS
      SELECT c.id AS call_id, c.workspace_id, c.agent_id, a.name AS agent_name, c.channel, c.status,
             c.disconnect_reason, coalesce(c.sentiment, 'unknown') AS sentiment,
             c.created_at AS started_at, coalesce(c.billable_seconds, 0) AS duration_s,
             c.cost_total_usd AS cost_usd
        FROM public.calls c JOIN public.agents a ON a.id = c.agent_id
       WHERE c.origin = 'live' AND c.workspace_id = {WS};

    CREATE OR REPLACE VIEW analytics.turn_latency_v WITH (security_barrier = true) AS
      SELECT e.workspace_id, e.call_id, c.agent_id, e.occurred_at, e.e2e_ms
        FROM public.call_events e JOIN public.calls c ON c.id = e.call_id
       WHERE e.type = 'turn' AND e.turn_index > 0 AND e.e2e_ms IS NOT NULL
         AND c.origin = 'live' AND e.workspace_id = {WS};

    -- Stub until 007 replaces it with the real per-call evaluator verdicts.
    CREATE OR REPLACE VIEW analytics.evaluator_verdicts_v WITH (security_barrier = true) AS
      SELECT NULL::text AS workspace_id, NULL::text AS call_id, NULL::text AS agent_id,
             NULL::text AS evaluator_name, NULL::text AS verdict, NULL::numeric AS score,
             NULL::timestamptz AS started_at
       WHERE false;

    GRANT SELECT ON analytics.calls_v, analytics.turn_latency_v, analytics.evaluator_verdicts_v
      TO cw_analytics_reader;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
