"""Voice runtime: calls, call events, pipeline steps, outbound webhooks, idempotency keys (003 T007).

Value sets from data-model.md (call_status, disconnect_reason, recording_status, ...) are text
columns with CHECK constraints, the same style as 001's ledger, so a new value is one constraint
change and drivers need no enum codecs.

``calls.agent_id`` and ``calls.agent_version_id`` carry no foreign keys yet: the agents tables
arrive with 002 in the same wave, and the integrator adds ``REFERENCES agents(id)`` and
``REFERENCES agent_versions(id) ON DELETE RESTRICT`` after both merge. ``call_costs.call_id``
(001) likewise gets its FK to ``calls`` then.

Revision ID: s003_0001
Revises: s001_0006
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s003_0001"
down_revision = "s001_0006"
branch_labels = None
depends_on = None


def _in(values: str) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values.split()) + ")"


CALL_STATUS = _in("queued ringing in_progress ended processing completed failed no_answer busy voicemail")
DISCONNECT_REASON = _in(
    "user_hangup agent_hangup call_transfer voicemail_reached inactivity max_duration_reached error "
    "concurrency_limit insufficient_credit"
)
EVENT_TYPE = _in("status turn transcript_item usage tool_call flow_transition dtmf warning error")
PIPELINE_STEP = _in("finalize_transcript price_and_charge analyze evaluate notify_analyzed complete")


def _rls(table: str) -> str:
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_tenant ON {table}
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    """


def upgrade() -> None:
    # calls ---------------------------------------------------------------------------------
    op.execute(f"""
    CREATE TABLE calls (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      agent_id text NOT NULL,
      agent_version_id text,
      origin text NOT NULL DEFAULT 'live' CHECK (origin IN ('live', 'test', 'simulation')),
      simulation_run_id text,
      channel text NOT NULL CHECK (channel IN ('web', 'sip_inbound', 'sip_outbound', 'whatsapp')),
      direction text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
      from_number text,
      to_number text,
      phone_number_id text,
      whatsapp_channel_id text,
      is_test boolean NOT NULL DEFAULT false,
      initiated_by_user_id text REFERENCES users(id),
      room_name text UNIQUE,
      sip_call_id text,
      status text NOT NULL CHECK (status IN {CALL_STATUS}),
      disconnect_reason text CHECK (disconnect_reason IN {DISCONNECT_REASON}),
      diagnostic text CHECK (char_length(diagnostic) <= 500),
      dynamic_variables jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      missing_variables text[] NOT NULL DEFAULT '{{}}',
      ignored_overrides text[] NOT NULL DEFAULT '{{}}',
      metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      idempotency_key text,
      created_at timestamptz NOT NULL DEFAULT now(),
      claimed_at timestamptz,
      ringing_at timestamptz,
      connected_at timestamptz,
      ended_at timestamptz,
      completed_at timestamptz,
      last_heartbeat_at timestamptz,
      billable_seconds integer CHECK (billable_seconds >= 0),
      usage jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      usage_seq integer NOT NULL DEFAULT 0,
      latency_stats jsonb,
      transcript jsonb,
      recording_enabled boolean NOT NULL DEFAULT true,
      recording_setting_source text NOT NULL DEFAULT 'workspace'
        CHECK (recording_setting_source IN ('workspace', 'agent')),
      recording_status text NOT NULL DEFAULT 'none'
        CHECK (recording_status IN ('none', 'recording', 'available', 'failed', 'not_recorded')),
      recording_key text,
      egress_id text,
      pipeline_status text NOT NULL DEFAULT 'not_started'
        CHECK (pipeline_status IN ('not_started', 'running', 'done', 'done_with_warnings', 'blocked')),
      pipeline_warnings text[] NOT NULL DEFAULT '{{}}',
      cost_total_usd numeric(18,6),
      cost_breakdown jsonb,
      summary text,
      sentiment text,
      analysis jsonb,
      worker_job_id text,
      CONSTRAINT calls_recording_consistency
        CHECK ((recording_status = 'not_recorded') = (NOT recording_enabled)),
      CONSTRAINT calls_metadata_size CHECK (octet_length(metadata::text) <= 4096),
      CONSTRAINT calls_simulation_run CHECK (simulation_run_id IS NULL OR origin = 'simulation')
    );
    CREATE INDEX ix_calls_active ON calls (workspace_id)
      WHERE status IN ('queued', 'ringing', 'in_progress');
    CREATE INDEX ix_calls_workspace_created ON calls (workspace_id, created_at DESC);
    CREATE INDEX ix_calls_agent_created ON calls (agent_id, created_at DESC);
    CREATE UNIQUE INDEX uq_calls_idempotency ON calls (workspace_id, idempotency_key)
      WHERE idempotency_key IS NOT NULL;
    CREATE INDEX ix_calls_heartbeat ON calls (status, last_heartbeat_at)
      WHERE status IN ('ringing', 'in_progress');
    CREATE INDEX ix_calls_queued ON calls (status, created_at) WHERE status = 'queued';
    CREATE INDEX ix_calls_egress ON calls (egress_id) WHERE egress_id IS NOT NULL;

    -- FR-043: the recording setting is resolved once at admission and never changes.
    CREATE FUNCTION calls_recording_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.recording_enabled IS DISTINCT FROM OLD.recording_enabled
         OR NEW.recording_setting_source IS DISTINCT FROM OLD.recording_setting_source THEN
        RAISE EXCEPTION 'calls.recording_enabled and recording_setting_source are immutable'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER calls_recording_immutable
      BEFORE UPDATE ON calls FOR EACH ROW EXECUTE FUNCTION calls_recording_immutable();
    {_rls("calls")}
    GRANT SELECT, INSERT, UPDATE ON calls TO callwright_app;
    """)

    # call_events ---------------------------------------------------------------------------
    op.execute(f"""
    CREATE TABLE call_events (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL,
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      seq integer NOT NULL CHECK (seq >= 1),
      type text NOT NULL CHECK (type IN {EVENT_TYPE}),
      occurred_at timestamptz NOT NULL,
      offset_ms integer,
      turn_index integer,
      stt_final_ms integer,
      eou_delay_ms integer,
      llm_ttft_ms integer,
      tts_ttfb_ms integer,
      e2e_ms integer,
      tool_ms integer,
      interrupted boolean,
      payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      CONSTRAINT uq_call_events_call_seq UNIQUE (call_id, seq)
    );
    CREATE INDEX ix_call_events_turns ON call_events (workspace_id, occurred_at) WHERE type = 'turn';
    {_rls("call_events")}
    GRANT SELECT, INSERT ON call_events TO callwright_app;
    """)

    # call_pipeline_steps -------------------------------------------------------------------
    op.execute(f"""
    CREATE TABLE call_pipeline_steps (
      call_id text NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
      step text NOT NULL CHECK (step IN {PIPELINE_STEP}),
      workspace_id text NOT NULL,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed', 'skipped')),
      blocking boolean NOT NULL,
      attempts integer NOT NULL DEFAULT 0,
      last_error text CHECK (char_length(last_error) <= 2048),
      started_at timestamptz,
      finished_at timestamptz,
      PRIMARY KEY (call_id, step)
    );
    {_rls("call_pipeline_steps")}
    GRANT SELECT, INSERT, UPDATE ON call_pipeline_steps TO callwright_app;
    """)

    # webhooks ------------------------------------------------------------------------------
    op.execute(f"""
    CREATE TABLE webhook_signing_secrets (
      workspace_id text PRIMARY KEY REFERENCES workspaces(id),
      current_secret_id bigint NOT NULL REFERENCES secrets(id),
      previous_secret_id bigint REFERENCES secrets(id),
      previous_expires_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      rotated_at timestamptz
    );
    {_rls("webhook_signing_secrets")}
    GRANT SELECT, INSERT, UPDATE ON webhook_signing_secrets TO callwright_app;

    CREATE TABLE webhook_deliveries (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      call_id text REFERENCES calls(id) ON DELETE CASCADE,
      event text NOT NULL CHECK (event IN ('call_started', 'call_ended', 'call_analyzed', 'ping')),
      url text NOT NULL CHECK (char_length(url) <= 2048),
      timeout_ms integer NOT NULL CHECK (timeout_ms BETWEEN 1000 AND 30000),
      body text NOT NULL,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivering', 'succeeded', 'failed', 'blocked')),
      attempts jsonb NOT NULL DEFAULT '[]'::jsonb,
      next_attempt_at timestamptz,
      redelivery_of text,
      created_at timestamptz NOT NULL DEFAULT now(),
      completed_at timestamptz,
      CONSTRAINT webhook_deliveries_ping_has_no_call CHECK ((event = 'ping') = (call_id IS NULL))
    );
    CREATE UNIQUE INDEX uq_webhook_deliveries_event ON webhook_deliveries (call_id, event)
      WHERE redelivery_of IS NULL AND event <> 'ping';
    CREATE INDEX ix_webhook_deliveries_workspace_created
      ON webhook_deliveries (workspace_id, created_at DESC);
    {_rls("webhook_deliveries")}
    GRANT SELECT, INSERT, UPDATE ON webhook_deliveries TO callwright_app;
    """)

    # idempotency_keys (core, created here: 001 did not need one) ------------------------------
    op.execute(f"""
    CREATE TABLE idempotency_keys (
      workspace_id text NOT NULL REFERENCES workspaces(id),
      endpoint text NOT NULL,
      key text NOT NULL CHECK (char_length(key) BETWEEN 1 AND 255),
      request_hash text NOT NULL,
      response_status integer,
      response_body jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours',
      PRIMARY KEY (workspace_id, endpoint, key)
    );
    {_rls("idempotency_keys")}
    GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys TO callwright_app;
    """)

    # Security-definer lookups for callers that start without a workspace context: internal
    # worker endpoints (workspace derived from the call row, never from the body), LiveKit
    # webhooks (room name, egress id) and the cross-workspace crons (reaper, purges).
    op.execute("""
    CREATE FUNCTION calls_workspace_for(p_call_id text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id FROM calls WHERE id = p_call_id
    $$;

    CREATE FUNCTION calls_for_room(p_room text)
    RETURNS TABLE (call_id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id FROM calls WHERE room_name = p_room
    $$;

    CREATE FUNCTION calls_for_egress(p_egress_id text)
    RETURNS TABLE (call_id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id FROM calls WHERE egress_id = p_egress_id
    $$;

    CREATE FUNCTION calls_stuck(p_queued_s integer, p_heartbeat_s integer)
    RETURNS TABLE (call_id text, workspace_id text, status text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id, status FROM calls
      WHERE (status = 'queued'
             AND created_at < now() - make_interval(secs => p_queued_s)
             AND (last_heartbeat_at IS NULL
                  OR last_heartbeat_at < now() - make_interval(secs => p_heartbeat_s)))
         OR (status IN ('ringing', 'in_progress')
             AND coalesce(last_heartbeat_at, claimed_at, created_at)
                 < now() - make_interval(secs => p_heartbeat_s))
      ORDER BY created_at
      LIMIT 500
    $$;

    CREATE FUNCTION webhook_deliveries_purge(p_days integer)
    RETURNS bigint
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $$
      WITH gone AS (
        DELETE FROM webhook_deliveries
        WHERE created_at < now() - make_interval(days => p_days)
        RETURNING 1
      )
      SELECT count(*) FROM gone
    $$;

    CREATE FUNCTION idempotency_keys_purge()
    RETURNS bigint
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $$
      WITH gone AS (DELETE FROM idempotency_keys WHERE expires_at < now() RETURNING 1)
      SELECT count(*) FROM gone
    $$;
    """)
    for fn in (
        "calls_workspace_for(text)",
        "calls_for_room(text)",
        "calls_for_egress(text)",
        "calls_stuck(integer, integer)",
        "webhook_deliveries_purge(integer)",
        "idempotency_keys_purge()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO callwright_app")


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
