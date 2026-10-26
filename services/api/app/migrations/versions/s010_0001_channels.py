"""Channels (010 T003, T074; data-model.md sections 1 to 9).

* ``phone_numbers``: bring-your-own SIP numbers with their LiveKit trunk and dispatch rule ids.
  A number is unique across every workspace while it is not deleted (FR-003).
* ``whatsapp_channels`` and ``whatsapp_caller_routes``: WhatsApp Business voice channels.
* ``dnc_entries``, ``outbound_calling_hours`` and ``outbound_policy_decisions``: outbound
  compliance (FR-034 to FR-038).
* ``calls`` gains ``ring_timeout_s``, ``route_detail``, foreign keys to the two channel tables
  and partial indexes for active-call counts.
* Secrets (carrier password, WhatsApp tokens, app secret, Meta SIP credentials) live in 001's
  ``secrets`` table; the columns here hold the secret's name only.
* Security-definer functions for callers that start without a workspace: inbound routing
  (research R4), the public WhatsApp webhook, global uniqueness checks and the drain cron. None
  of them returns a secret.

Revision ID: s010_0001
Revises: s006_0001 (the integrator re-chains it at the wave 3b merge)
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "s010_0001"
down_revision = "s006_0001"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
    "phone_numbers",
    "whatsapp_channels",
    "whatsapp_caller_routes",
    "dnc_entries",
    "outbound_calling_hours",
    "outbound_policy_decisions",
)

_FUNCTIONS = (
    "route_phone_number(text)",
    "route_whatsapp_channel(text, text)",
    "lookup_whatsapp_channel_by_verify_hash(text)",
    "lookup_whatsapp_channel_by_meta_id(text)",
    "phone_number_e164_status(text)",
    "whatsapp_meta_id_in_use(text)",
    "whatsapp_verify_hash_in_use(text)",
    "channels_draining()",
)


def upgrade() -> None:
    op.execute("""
    CREATE TYPE sip_transport AS ENUM ('auto', 'udp', 'tcp', 'tls');
    CREATE TYPE channel_status AS ENUM ('provisioning', 'active', 'error', 'draining', 'deleted');
    CREATE TYPE whatsapp_channel_status AS ENUM
      ('setup_incomplete', 'active', 'error', 'draining', 'deleted');
    CREATE TYPE dnc_source AS ENUM ('manual', 'csv_import');
    CREATE TYPE outbound_block_reason AS ENUM ('dnc_listed', 'outside_calling_hours');
    CREATE TYPE timezone_source AS ENUM ('override', 'number_region', 'unknown');

    CREATE TABLE phone_numbers (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      e164 text NOT NULL CHECK (e164 ~ '^\\+[1-9][0-9]{6,14}$'),
      label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 100),
      termination_host text NOT NULL CHECK (char_length(termination_host) BETWEEN 1 AND 255),
      termination_port integer CHECK (termination_port BETWEEN 1 AND 65535),
      transport sip_transport NOT NULL DEFAULT 'auto',
      auth_username text CHECK (char_length(auth_username) <= 128),
      auth_password_secret text,
      inbound_allowed_cidrs cidr[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(inbound_allowed_cidrs) <= 20),
      inbound_agent_id text REFERENCES agents(id) ON DELETE SET NULL,
      outbound_agent_id text REFERENCES agents(id) ON DELETE SET NULL,
      inbound_webhook_url text CHECK (char_length(inbound_webhook_url) <= 2048),
      lk_inbound_trunk_id text,
      lk_outbound_trunk_id text,
      lk_dispatch_rule_id text,
      status channel_status NOT NULL DEFAULT 'provisioning',
      status_detail text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz,
      CONSTRAINT phone_numbers_deleted_status CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
    );
    CREATE UNIQUE INDEX uq_phone_numbers_e164 ON phone_numbers (e164) WHERE deleted_at IS NULL;
    CREATE INDEX ix_phone_numbers_workspace_created ON phone_numbers (workspace_id, created_at DESC);
    CREATE INDEX ix_phone_numbers_inbound_agent ON phone_numbers (inbound_agent_id)
      WHERE inbound_agent_id IS NOT NULL;
    CREATE INDEX ix_phone_numbers_outbound_agent ON phone_numbers (outbound_agent_id)
      WHERE outbound_agent_id IS NOT NULL;

    CREATE TABLE whatsapp_channels (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      meta_phone_number_id text NOT NULL CHECK (meta_phone_number_id ~ '^[0-9]{5,32}$'),
      e164 text NOT NULL CHECK (e164 ~ '^\\+[1-9][0-9]{6,14}$'),
      label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 100),
      access_token_secret text NOT NULL,
      access_token_last4 text NOT NULL,
      verify_token_secret text NOT NULL,
      verify_token_last4 text NOT NULL,
      verify_token_hash text NOT NULL CHECK (verify_token_hash ~ '^[0-9a-f]{64}$'),
      app_secret_secret text NOT NULL,
      graph_api_version text NOT NULL CHECK (graph_api_version ~ '^v?[0-9]+\\.[0-9]+$'),
      sip_credentials_secret text,
      inbound_agent_id text REFERENCES agents(id) ON DELETE SET NULL,
      inbound_webhook_url text CHECK (char_length(inbound_webhook_url) <= 2048),
      lk_inbound_trunk_id text,
      lk_dispatch_rule_id text,
      status whatsapp_channel_status NOT NULL DEFAULT 'setup_incomplete',
      status_detail text,
      credentials_verified_at timestamptz,
      calling_enabled_at timestamptz,
      webhook_verified_at timestamptz,
      last_webhook_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz,
      CONSTRAINT whatsapp_channels_deleted_status CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
    );
    CREATE UNIQUE INDEX uq_whatsapp_channels_meta_id ON whatsapp_channels (meta_phone_number_id)
      WHERE deleted_at IS NULL;
    CREATE UNIQUE INDEX uq_whatsapp_channels_verify_hash ON whatsapp_channels (verify_token_hash)
      WHERE deleted_at IS NULL;
    CREATE INDEX ix_whatsapp_channels_workspace_created
      ON whatsapp_channels (workspace_id, created_at DESC);

    CREATE TABLE whatsapp_caller_routes (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      channel_id text NOT NULL REFERENCES whatsapp_channels(id) ON DELETE CASCADE,
      caller_e164 text NOT NULL CHECK (caller_e164 ~ '^\\+[1-9][0-9]{6,14}$'),
      agent_id text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_whatsapp_caller_routes_caller UNIQUE (channel_id, caller_e164)
    );
    CREATE INDEX ix_whatsapp_caller_routes_caller_prefix
      ON whatsapp_caller_routes (channel_id, caller_e164 text_pattern_ops);
    CREATE INDEX ix_whatsapp_caller_routes_agent ON whatsapp_caller_routes (agent_id);

    CREATE TABLE dnc_entries (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      e164 text NOT NULL CHECK (e164 ~ '^\\+[1-9][0-9]{6,14}$'),
      note text CHECK (char_length(note) <= 200),
      source dnc_source NOT NULL,
      import_batch_id text,
      created_by_user_id text REFERENCES users(id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_dnc_entries_number UNIQUE (workspace_id, e164)
    );
    CREATE INDEX ix_dnc_entries_workspace_created ON dnc_entries (workspace_id, created_at DESC);
    CREATE INDEX ix_dnc_entries_e164_prefix ON dnc_entries (workspace_id, e164 text_pattern_ops);

    CREATE TABLE outbound_calling_hours (
      workspace_id text PRIMARY KEY REFERENCES workspaces(id),
      windows jsonb NOT NULL,
      updated_by_user_id text REFERENCES users(id) ON DELETE SET NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE outbound_policy_decisions (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      decided_at timestamptz NOT NULL DEFAULT now(),
      reason outbound_block_reason NOT NULL,
      to_number text NOT NULL,
      from_number text NOT NULL,
      phone_number_id text,
      agent_id text,
      requested_by text NOT NULL,
      idempotency_key text,
      dnc_entry_id text,
      dnc_e164 text,
      recipient_timezones text[],
      timezone_source timezone_source,
      recipient_local_time timestamp,
      next_allowed_at timestamptz
    );
    CREATE INDEX ix_outbound_policy_decisions_workspace_decided
      ON outbound_policy_decisions (workspace_id, decided_at DESC);
    CREATE INDEX ix_outbound_policy_decisions_workspace_to
      ON outbound_policy_decisions (workspace_id, to_number);
    """)
    for table in _TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON {table}
          USING (workspace_id = current_setting('app.workspace_id', true))
          WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO callwright_app;
        """)

    # calls (003's table): ring timeout, routing outcome, channel foreign keys -----------------
    op.execute("""
    ALTER TABLE calls
      ADD COLUMN ring_timeout_s smallint CHECK (ring_timeout_s BETWEEN 10 AND 60),
      ADD COLUMN route_detail text CHECK (char_length(route_detail) <= 200),
      ADD CONSTRAINT fk_calls_phone_number FOREIGN KEY (phone_number_id)
        REFERENCES phone_numbers(id) ON DELETE RESTRICT,
      ADD CONSTRAINT fk_calls_whatsapp_channel FOREIGN KEY (whatsapp_channel_id)
        REFERENCES whatsapp_channels(id) ON DELETE RESTRICT;
    CREATE INDEX ix_calls_phone_number_active ON calls (phone_number_id)
      WHERE status IN ('queued', 'ringing', 'in_progress');
    CREATE INDEX ix_calls_whatsapp_channel_active ON calls (whatsapp_channel_id)
      WHERE status IN ('queued', 'ringing', 'in_progress');
    """)

    # Security-definer functions (research R4). They return routing columns only, never secrets.
    op.execute("""
    CREATE FUNCTION route_phone_number(p_number_id text)
    RETURNS TABLE (workspace_id text, e164 text, status text, inbound_agent_id text,
                   inbound_webhook_url text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id, e164, status::text, inbound_agent_id, inbound_webhook_url
      FROM phone_numbers WHERE id = p_number_id AND deleted_at IS NULL
    $$;

    CREATE FUNCTION route_whatsapp_channel(p_channel_id text, p_caller_e164 text)
    RETURNS TABLE (workspace_id text, e164 text, status text, default_agent_id text,
                   route_agent_id text, inbound_webhook_url text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT c.workspace_id, c.e164, c.status::text, c.inbound_agent_id,
        (SELECT r.agent_id FROM whatsapp_caller_routes r
          WHERE r.channel_id = c.id AND r.caller_e164 = p_caller_e164),
        c.inbound_webhook_url
      FROM whatsapp_channels c WHERE c.id = p_channel_id AND c.deleted_at IS NULL
    $$;

    CREATE FUNCTION lookup_whatsapp_channel_by_verify_hash(p_hash text)
    RETURNS TABLE (channel_id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id FROM whatsapp_channels
      WHERE verify_token_hash = p_hash AND deleted_at IS NULL
    $$;

    CREATE FUNCTION lookup_whatsapp_channel_by_meta_id(p_meta_id text)
    RETURNS TABLE (channel_id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT id, workspace_id FROM whatsapp_channels
      WHERE meta_phone_number_id = p_meta_id AND deleted_at IS NULL
    $$;

    -- Global uniqueness checks that reveal nothing about the other workspace.
    CREATE FUNCTION phone_number_e164_status(p_e164 text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT status::text FROM phone_numbers WHERE e164 = p_e164 AND deleted_at IS NULL
    $$;

    CREATE FUNCTION whatsapp_meta_id_in_use(p_meta_id text)
    RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT EXISTS (SELECT 1 FROM whatsapp_channels
                     WHERE meta_phone_number_id = p_meta_id AND deleted_at IS NULL)
    $$;

    CREATE FUNCTION whatsapp_verify_hash_in_use(p_hash text)
    RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT EXISTS (SELECT 1 FROM whatsapp_channels
                     WHERE verify_token_hash = p_hash AND deleted_at IS NULL)
    $$;

    -- Drain cleanup (research R8): every draining number and channel, any workspace.
    CREATE FUNCTION channels_draining()
    RETURNS TABLE (kind text, id text, workspace_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT 'phone_number', id, workspace_id FROM phone_numbers WHERE status = 'draining'
      UNION ALL
      SELECT 'whatsapp_channel', id, workspace_id FROM whatsapp_channels WHERE status = 'draining'
    $$;
    """)
    for fn in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO callwright_app")


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
