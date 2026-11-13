"""Account deletion with a grace period (account feature).

* ``users.deletion_requested_at`` / ``deletion_scheduled_at``: the owner asked for deletion; the
  erase job removes the account once ``deletion_scheduled_at`` has passed. Cancelling clears both.
* ``workspaces.deleted_at`` and a nullable ``owner_user_id`` (``ON DELETE SET NULL``): erasing an
  account keeps a *tombstone* workspace row (name blanked, no owner) because the billing ledger
  (``credit_transactions``, ``usage_events``, ``checkout_sessions``, ``call_costs``) is kept for
  accounting and references the workspace id.
* ``call_costs.call_id`` stops referencing ``calls``: the cost row outlives the erased call.
* ``app_resolve_subject`` also returns ``deletion_scheduled_at`` (the API lock reads it).
* ``account_erasure_due()`` and ``app_erase_workspace()`` are security-definer functions for the
  jobs worker's admin role. The erase deletes every row of every table that has a
  ``workspace_id`` column (found in the catalog, so a table added later is covered without a code
  change), children before parents, except the ledger tables above.
* ``local_idp.users.password_set``: false for accounts created through Google sign-in.

Revision ID: s024_0001
Revises: s022_0001
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op

revision = "s024_0001"
down_revision = "s022_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE users
      ADD COLUMN deletion_requested_at timestamptz,
      ADD COLUMN deletion_scheduled_at timestamptz;
    CREATE INDEX ix_users_deletion_due ON users (deletion_scheduled_at)
      WHERE deletion_scheduled_at IS NOT NULL;
    GRANT UPDATE (deletion_requested_at, deletion_scheduled_at) ON users TO callwright_app;

    ALTER TABLE workspaces ADD COLUMN deleted_at timestamptz;
    ALTER TABLE workspaces ALTER COLUMN owner_user_id DROP NOT NULL;
    ALTER TABLE workspaces DROP CONSTRAINT workspaces_owner_user_id_fkey;
    ALTER TABLE workspaces ADD CONSTRAINT workspaces_owner_user_id_fkey
      FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL;

    ALTER TABLE call_costs DROP CONSTRAINT fk_call_costs_call;

    ALTER TABLE local_idp.users ADD COLUMN password_set boolean NOT NULL DEFAULT true;

    DROP FUNCTION app_resolve_subject(text);
    CREATE FUNCTION app_resolve_subject(p_subject text)
    RETURNS TABLE (user_id text, workspace_id text, email text, email_verified boolean, is_admin boolean,
                   deletion_scheduled_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT u.id, w.id, u.email::text, u.email_verified_at IS NOT NULL, u.is_admin,
             u.deletion_scheduled_at
      FROM users u LEFT JOIN workspaces w ON w.owner_user_id = u.id
      WHERE u.idp_subject = p_subject
    $$;
    REVOKE ALL ON FUNCTION app_resolve_subject(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_resolve_subject(text) TO callwright_app;

    -- Accounts whose grace period is over (ids only; the worker then works per account).
    CREATE FUNCTION account_erasure_due(p_limit int)
    RETURNS TABLE (user_id text, workspace_id text, idp_subject text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
      SELECT u.id, w.id, u.idp_subject
      FROM users u LEFT JOIN workspaces w ON w.owner_user_id = u.id
      WHERE u.deletion_scheduled_at IS NOT NULL AND u.deletion_scheduled_at <= now()
      ORDER BY u.deletion_scheduled_at
      LIMIT p_limit
    $$;
    REVOKE ALL ON FUNCTION account_erasure_due(int) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION account_erasure_due(int) TO callwright_admin;

    -- Erase one account's data. Idempotent: a second run finds nothing left to delete.
    CREATE FUNCTION app_erase_workspace(p_workspace_id text, p_user_id text)
    RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      keep text[] := ARRAY['credit_transactions', 'usage_events', 'checkout_sessions', 'call_costs',
                           'workspaces'];
      remaining regclass[];
      ready regclass[];
      t regclass;
      n bigint;
      counts jsonb := '{}'::jsonb;
    BEGIN
      -- Row level security is forced on tenant tables; the owner's policies see this workspace.
      PERFORM set_config('app.workspace_id', p_workspace_id, true);
      PERFORM set_config('app.user_id', p_user_id, true);

      SELECT coalesce(array_agg(c.oid::regclass ORDER BY c.relname), ARRAY[]::regclass[])
        INTO remaining
        FROM pg_class c
        JOIN pg_namespace ns ON ns.oid = c.relnamespace AND ns.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'workspace_id' AND NOT a.attisdropped
       WHERE c.relkind IN ('r', 'p') AND c.relname <> ALL (keep);

      WHILE cardinality(remaining) > 0 LOOP
        -- Delete first the tables no other remaining table still points at through an immediate
        -- (non-deferrable, no cascade) foreign key. Deferrable and cascading references need no order.
        SELECT coalesce(array_agg(r), ARRAY[]::regclass[]) INTO ready
          FROM unnest(remaining) AS r
         WHERE NOT EXISTS (
           SELECT 1 FROM pg_constraint k
            WHERE k.contype = 'f' AND k.confrelid = r AND k.conrelid = ANY (remaining)
              AND k.conrelid <> r AND NOT k.condeferrable AND k.confdeltype IN ('a', 'r'));
        IF cardinality(ready) = 0 THEN
          ready := remaining;
        END IF;
        FOREACH t IN ARRAY ready LOOP
          EXECUTE format('DELETE FROM %s WHERE workspace_id = $1', t) USING p_workspace_id;
          GET DIAGNOSTICS n = ROW_COUNT;
          IF n > 0 THEN
            counts := counts || jsonb_build_object(t::text, n);
          END IF;
          remaining := array_remove(remaining, t);
        END LOOP;
      END LOOP;

      -- Tombstone: the ledger keeps pointing at this id, with no name and no owner.
      UPDATE workspaces SET name = '[deleted]', owner_user_id = NULL, deleted_at = coalesce(deleted_at, now())
       WHERE id = p_workspace_id;
      DELETE FROM users WHERE id = p_user_id;
      GET DIAGNOSTICS n = ROW_COUNT;
      counts := counts || jsonb_build_object('users', n);
      RETURN counts;
    END $$;
    REVOKE ALL ON FUNCTION app_erase_workspace(text, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_erase_workspace(text, text) TO callwright_admin;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
