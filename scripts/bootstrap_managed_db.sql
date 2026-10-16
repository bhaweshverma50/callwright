-- Prepare a managed Postgres (Supabase) for the Callwright migrations. Idempotent: run it again
-- to rotate the role passwords.
--
-- Run it once per database, before the first `migrate`, over a session connection (the direct
-- connection or Supabase's session pooler on port 5432, never the transaction pooler on 6543),
-- as the role that will run migrations (`postgres` on Supabase):
--
--   psql "postgresql://postgres.<ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
--     -v ON_ERROR_STOP=1 \
--     -v app_password="$CALLWRIGHT_APP_DB_PASSWORD" \
--     -v admin_password="$CALLWRIGHT_ADMIN_DB_PASSWORD" \
--     -f scripts/bootstrap_managed_db.sql
--
-- What it does:
--   1. checks the current role can create roles and bypasses RLS (the migrations' security
--      definer lookups read across workspaces as the table owner);
--   2. makes sure citext and vector are installed in schema public (the RLS lookup functions pin
--      search_path = public, so citext operators must resolve there);
--   3. creates or updates the login roles the API connects as:
--        callwright_app    every tenant query; subject to RLS (NOBYPASSRLS)
--        callwright_admin  global pricing catalog writes and maintenance reads (NOBYPASSRLS)
--      Tables, functions and grants come from the migrations, which skip role creation when the
--      roles exist, so APP_DB_PASSWORD / ADMIN_DB_PASSWORD are not needed by the migrate job;
--   4. grants CONNECT on this database to both roles.

\set ON_ERROR_STOP on

\if :{?app_password}
\else
  DO $$ BEGIN RAISE EXCEPTION 'missing psql variable: -v app_password=...'; END $$;
\endif
\if :{?admin_password}
\else
  DO $$ BEGIN RAISE EXCEPTION 'missing psql variable: -v admin_password=...'; END $$;
\endif

-- 1. The migrating role ----------------------------------------------------------------------
DO $$
DECLARE
  r record;
BEGIN
  SELECT rolsuper, rolcreaterole, rolbypassrls INTO r FROM pg_roles WHERE rolname = current_user;
  IF NOT (r.rolsuper OR (r.rolcreaterole AND r.rolbypassrls)) THEN
    RAISE EXCEPTION 'role % needs CREATEROLE and BYPASSRLS (or superuser) to run the migrations', current_user;
  END IF;
END $$;

-- 2. Extensions in schema public ------------------------------------------------------------
-- A dashboard may have enabled them in schema "extensions"; move them (allowed while no table
-- uses them yet, and only for the extension owner).
SELECT format('ALTER EXTENSION %I SET SCHEMA public', e.extname)
FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
WHERE e.extname IN ('citext', 'vector') AND n.nspname <> 'public'
\gexec
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- 3. Login roles ----------------------------------------------------------------------------
SELECT format('CREATE ROLE %I LOGIN NOBYPASSRLS', name)
FROM (VALUES ('callwright_app'), ('callwright_admin')) AS roles(name)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = roles.name)
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN NOBYPASSRLS PASSWORD %L', 'callwright_app', :'app_password')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN NOBYPASSRLS PASSWORD %L', 'callwright_admin', :'admin_password')
\gexec

-- 4. Database access (PUBLIC usually has CONNECT already; only the owner can always grant it)
DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO callwright_app, callwright_admin', current_database());
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'GRANT CONNECT skipped: %', SQLERRM;
END $$;

SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles
WHERE rolname IN ('callwright_app', 'callwright_admin') ORDER BY rolname;
