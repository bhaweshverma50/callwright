"""Foundation: roles, users, workspaces, the credit ledger, usage events, lookup functions.

Revision ID: s001_0001
Revises:
Create Date: 2026-10-16
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "s001_0001"
down_revision = None
branch_labels = None
depends_on = None

LOCAL_ENVS = ("dev", "test")


def _role(name: str, password_var: str, local_default: str) -> None:
    """Create the login role unless it exists (managed databases get theirs from the bootstrap SQL).

    The password comes from ``password_var``. The well-known local default is used only for ENV
    dev or test: anywhere else a missing password stops the migration rather than create a role
    anyone can guess.
    """
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": name}).first():
        return
    password = os.environ.get(password_var)
    if not password:
        from app.core.config import get_settings

        if get_settings().env not in LOCAL_ENVS:
            raise RuntimeError(f"Role {name} does not exist: set {password_var} to create it.")
        password = local_default
    quoted = password.replace("'", "''")
    op.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{quoted}' NOBYPASSRLS")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _role("callwright_app", "APP_DB_PASSWORD", "callwright_app")
    _role("callwright_admin", "ADMIN_DB_PASSWORD", "callwright_admin")
    # On managed Postgres the migrating role may not own the database; PUBLIC keeps CONNECT by
    # default there and scripts/bootstrap_managed_db.sql grants it, so a refusal is not fatal.
    op.execute("""
    DO $$
    BEGIN
      EXECUTE format('GRANT CONNECT ON DATABASE %I TO callwright_app, callwright_admin', current_database());
    EXCEPTION WHEN insufficient_privilege THEN
      RAISE NOTICE 'GRANT CONNECT skipped: % (grant it as the database owner if PUBLIC lacks CONNECT)', SQLERRM;
    END $$;
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO callwright_app, callwright_admin")

    # users -------------------------------------------------------------------------------
    op.execute("""
    CREATE TABLE users (
      id text PRIMARY KEY,
      idp_subject text NOT NULL UNIQUE,
      email citext NOT NULL UNIQUE,
      email_verified_at timestamptz,
      is_admin boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE users ENABLE ROW LEVEL SECURITY;
    ALTER TABLE users FORCE ROW LEVEL SECURITY;
    CREATE POLICY users_self ON users
      USING (id = current_setting('app.user_id', true))
      WITH CHECK (id = current_setting('app.user_id', true));
    GRANT SELECT, INSERT ON users TO callwright_app;
    """)

    # workspaces --------------------------------------------------------------------------
    op.execute("""
    CREATE TABLE workspaces (
      id text PRIMARY KEY,
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
      owner_user_id text NOT NULL UNIQUE REFERENCES users(id),
      concurrency_limit integer NOT NULL DEFAULT 5 CHECK (concurrency_limit BETWEEN 1 AND 500),
      recording_default boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
    ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
    CREATE POLICY workspaces_tenant ON workspaces
      USING (id = current_setting('app.workspace_id', true))
      WITH CHECK (id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON workspaces TO callwright_app;
    GRANT UPDATE (name, recording_default) ON workspaces TO callwright_app;
    """)

    # credit_transactions: append-only ledger (R10) -----------------------------------------
    op.execute("""
    CREATE TABLE credit_transactions (
      id text PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      seq bigint NOT NULL,
      type text NOT NULL CHECK (type IN
        ('top_up', 'call_charge', 'feature_charge', 'trial_grant', 'refund', 'adjustment')),
      amount_usd numeric(18,6) NOT NULL,
      balance_after_usd numeric(18,6) NOT NULL,
      call_id text,
      feature_key text,
      external_ref text UNIQUE,
      idempotency_key text,
      description text NOT NULL CHECK (char_length(description) <= 200),
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT sign_rule CHECK (
        (type IN ('top_up', 'trial_grant', 'refund') AND amount_usd > 0)
        OR (type IN ('call_charge', 'feature_charge') AND amount_usd < 0)
        OR (type = 'adjustment' AND amount_usd <> 0)
      ),
      CONSTRAINT seq_positive CHECK (seq >= 1),
      CONSTRAINT uq_credit_transactions_workspace_seq UNIQUE (workspace_id, seq),
      CONSTRAINT uq_credit_transactions_idempotency UNIQUE (workspace_id, idempotency_key)
    );
    CREATE UNIQUE INDEX uq_credit_transactions_trial_grant
      ON credit_transactions (workspace_id) WHERE type = 'trial_grant';
    CREATE UNIQUE INDEX uq_credit_transactions_call_charge
      ON credit_transactions (call_id) WHERE type = 'call_charge';
    CREATE INDEX ix_credit_transactions_workspace_created
      ON credit_transactions (workspace_id, created_at DESC);

    CREATE FUNCTION credit_transactions_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF current_user <> (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = TG_RELID) THEN
        RAISE EXCEPTION 'credit_transactions is append-only (% refused)', TG_OP
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER credit_transactions_immutable
      BEFORE UPDATE OR DELETE ON credit_transactions
      FOR EACH ROW EXECUTE FUNCTION credit_transactions_immutable();

    ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE credit_transactions FORCE ROW LEVEL SECURITY;
    CREATE POLICY credit_transactions_tenant ON credit_transactions
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON credit_transactions TO callwright_app;
    """)

    # usage_events (R14, FR-023) -------------------------------------------------------------
    op.execute("""
    CREATE TABLE usage_events (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id text NOT NULL REFERENCES workspaces(id),
      feature_key text NOT NULL,
      quantity numeric(18,6) NOT NULL CHECK (quantity >= 0),
      unit text NOT NULL,
      raw_cost_usd numeric(18,6) NOT NULL CHECK (raw_cost_usd >= 0),
      billable_cost_usd numeric(18,6) NOT NULL CHECK (billable_cost_usd >= 0),
      ref_type text,
      ref_id text,
      txn_id text REFERENCES credit_transactions(id),
      idempotency_key text,
      occurred_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT txn_iff_billable CHECK ((txn_id IS NULL) = (billable_cost_usd = 0))
    );
    CREATE INDEX ix_usage_events_workspace_occurred ON usage_events (workspace_id, occurred_at);
    CREATE UNIQUE INDEX uq_usage_events_txn ON usage_events (txn_id) WHERE txn_id IS NOT NULL;
    CREATE UNIQUE INDEX uq_usage_events_idempotency
      ON usage_events (workspace_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
    CREATE UNIQUE INDEX uq_usage_events_zero_ref
      ON usage_events (workspace_id, feature_key, coalesce(ref_type, ''), coalesce(ref_id, ''))
      WHERE txn_id IS NULL AND idempotency_key IS NULL;
    ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE usage_events FORCE ROW LEVEL SECURITY;
    CREATE POLICY usage_events_tenant ON usage_events
      USING (workspace_id = current_setting('app.workspace_id', true))
      WITH CHECK (workspace_id = current_setting('app.workspace_id', true));
    GRANT SELECT, INSERT ON usage_events TO callwright_app;
    """)

    # Security-definer lookups. They run as the owner (BYPASSRLS) and return only what the
    # caller needs to establish its RLS context.
    op.execute("""
    CREATE FUNCTION app_resolve_subject(p_subject text)
    RETURNS TABLE (user_id text, workspace_id text, email text, email_verified boolean, is_admin boolean)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT u.id, w.id, u.email::text, u.email_verified_at IS NOT NULL, u.is_admin
      FROM users u LEFT JOIN workspaces w ON w.owner_user_id = u.id
      WHERE u.idp_subject = p_subject
    $$;
    REVOKE ALL ON FUNCTION app_resolve_subject(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_resolve_subject(text) TO callwright_app;

    CREATE FUNCTION app_workspace_owner_verified(p_workspace_id text)
    RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT coalesce(
        (SELECT u.email_verified_at IS NOT NULL
         FROM workspaces w JOIN users u ON u.id = w.owner_user_id
         WHERE w.id = p_workspace_id),
        false)
    $$;
    REVOKE ALL ON FUNCTION app_workspace_owner_verified(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_workspace_owner_verified(text) TO callwright_app;

    CREATE FUNCTION billing_workspace_for_external_ref(p_ref text)
    RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT workspace_id FROM credit_transactions WHERE external_ref = p_ref
    $$;
    REVOKE ALL ON FUNCTION billing_workspace_for_external_ref(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION billing_workspace_for_external_ref(text) TO callwright_app;

    CREATE FUNCTION billing_reconcile()
    RETURNS TABLE (workspace_id text, row_count bigint, sum_usd numeric, balance_usd numeric, chain_breaks bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      WITH ordered AS (
        SELECT t.workspace_id, t.seq, t.amount_usd, t.balance_after_usd,
               lag(t.balance_after_usd, 1, 0::numeric) OVER w AS prev_balance,
               lag(t.seq, 1, 0::bigint) OVER w AS prev_seq
        FROM credit_transactions t
        WINDOW w AS (PARTITION BY t.workspace_id ORDER BY t.seq)
      )
      SELECT o.workspace_id,
             count(*),
             sum(o.amount_usd),
             (array_agg(o.balance_after_usd ORDER BY o.seq DESC))[1],
             count(*) FILTER (WHERE o.balance_after_usd <> o.prev_balance + o.amount_usd
                                 OR o.seq <> o.prev_seq + 1)
      FROM ordered o GROUP BY o.workspace_id
    $$;
    REVOKE ALL ON FUNCTION billing_reconcile() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION billing_reconcile() TO callwright_admin;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
