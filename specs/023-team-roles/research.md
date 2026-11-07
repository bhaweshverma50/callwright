# Research: Workspace team and roles (023)

Code facts below were read on 2026-11-07 at `49f36ee`. Paths are relative to the repository root.

## Current state

- Every request runs `current_principal` (`services/api/app/core/auth.py`), which calls the SQL
  function `app_resolve_subject(:sub)`. That function joins `users` to `workspaces` on
  `workspaces.owner_user_id` (`s001_0001_foundation.py`), so a user has at most one workspace.
  `owner_user_id` is `NOT NULL UNIQUE`.
- `Principal` carries `user_id`, `workspace_id`, `email`, `email_verified`, `is_admin`,
  `session_id` and `token_expires_at`. The only role is the platform flag `users.is_admin`
  (`require_admin`, used by the pricing router).
- RLS: `set_rls_context` (`services/api/app/core/db.py`) sets `app.workspace_id` and
  `app.user_id` per transaction; every tenant table has a `<table>_tenant` policy on
  `workspace_id`. The newest migration is `s013_0001` (`s<spec>_<seq>_<slug>.py`, forward-only).
- Revocation: a Redis key `auth:revoked:{session_id}` blocks one session until its token expires
  (access tokens live 3,600 s). Other sessions of a user stay valid until expiry.
- Calls are read by `calls/queries.py` (`conditions()` for list and export), but also directly by
  `live_calls`, `call_detail`, `dashboard/service.py`, `review/service.py`, `issues/detection.py`,
  `issues/validation.py`, `analytics_chat/query_compiler.py`, `call_events/service.py`,
  `evals/embeddings.py` and annotations.
- The API sends no email. The local IdP logs verify and reset mails to a dev outbox
  (`GET /v1/dev/mail`); Supabase sends its own auth mails.
- The web polls (`LIVE_POLL_MS=3000`); there is no push channel. `useMe()` loads `GET /me`;
  tokens live in localStorage; `npm run gen:api` builds types from `specs/*/contracts/*.yaml`.
- Workspace API keys do not exist (spec 023 edge case and FR-006 row refer to them as future).

## R1. Membership and the current workspace

- **Decision**: New table `workspace_members (workspace_id, user_id, roles text[], status,
  invited_by, joined_at, removed_at, revision)`. The owner stays in `workspaces.owner_user_id`
  (exactly one owner per workspace is then structural) and also has a member row whose roles
  always include `supervisor`. `roles` holds only `admin`, `builder`, `supervisor`, `analyst`;
  "owner" is derived. Drop the `UNIQUE` on `owner_user_id` so a person can own several
  workspaces. `app_resolve_subject(:sub, :workspace_id)` returns the user, the chosen workspace,
  `is_owner` and `roles`, only for an `active` membership.
- **Choosing the workspace**: the web sends `Callwright-Workspace: ws_...` on every request. When
  the header is missing, the API uses `users.last_workspace_id` if still a member, else the
  oldest active membership. Switching calls `PUT /me/workspace`, which stores
  `last_workspace_id`.
- **Rationale**: The token comes from the IdP (Supabase in production), so a workspace claim
  cannot be added to it without a custom hook; a header keeps both IdPs unchanged. Deriving the
  owner from `workspaces` avoids a second source of truth and a partial unique index.
- **Alternatives**: Workspace in the JWT (needs IdP hooks and a token refresh on every switch);
  one row per (user, workspace, role) (more rows, harder concurrency checks); owner as a role in
  the array (needs a partial unique index and a transfer that touches two rows anyway).

## R2. Access table in code, enforced per route

- **Decision**: `core/permissions.py` holds one dict from permission name to the roles that grant
  it (FR-006), for example `billing.pay: {owner}`, `team.manage: {owner, admin}`,
  `agents.publish: {owner, admin, builder}`, `calls.read: {owner, admin, builder, supervisor,
  analyst}`, `live.intervene: {supervisor}`. A FastAPI dependency `require(permission)` returns
  the principal or raises 403 problem+json `forbidden` with `detail` naming who can grant
  access (FR-008). `GET /me` returns the effective permission list, so the web hides controls
  from the same table and never duplicates it.
- **Route guard test**: an architecture test walks `app.routes` and fails when a `/v1` route
  neither depends on `require(...)` nor sits in a short allowlist (auth, public invitation
  preview, internal service routes, dev routes, webhooks).
- **Rationale**: One table answers "who can do what" and is testable row by row (SC-002).
- **Alternatives**: Policy engine (Oso, Casbin): a dependency and a DSL for 5 fixed roles;
  checks inside services: easy to miss, and not testable as a sweep.

## R3. Supervisor scoping at the database layer

- **Decision**: A new setting `app.agent_scope` holds `*` when the principal holds any role that
  reads every agent (owner, admin, builder, analyst), otherwise a comma list of the agent ids
  assigned to them (an empty string when none). `current_principal` stores the scope in a
  request context variable and `set_rls_context` reads it, so every request transaction gets
  it without router changes; jobs and other system transactions have no request context and
  get `*`.
- **Policies**: `s023_0001` adds a `RESTRICTIVE` policy `<table>_agent_scope` next to each
  `_tenant` policy:
  - tables with `agent_id`: `agents` (on `id`), `agent_versions`, `flows`, `calls`,
    `evaluator_runs`, `call_embeddings`, `issues`, `issue_detection_runs`, `test_cases`,
    `test_runs`, `simulation_experiments`, `simulation_runs`, `datasets`,
    `scheduled_callbacks`:
    `USING (current_setting('app.agent_scope', true) = '*' OR agent_id = ANY
    (string_to_array(current_setting('app.agent_scope', true), ',')))`;
  - tables keyed by `call_id`: `call_events`, `call_pipeline_steps`, `call_analyses`,
    `call_languages`, `call_costs`, `annotations`, `evaluator_run_groups`, `issue_samples`,
    `dataset_items`, `webhook_deliveries`:
    `USING (current_setting('app.agent_scope', true) = '*' OR EXISTS (SELECT 1 FROM calls c
    WHERE c.id = call_id))`, which inherits the `calls` policy.
  A missing setting is `NULL`, which matches nothing, so an app-role transaction that somehow
  skipped the context fails closed.
- **Rationale**: Constitution V asks for isolation at the database layer. More than eight
  modules read call data directly (list, live, detail, export, dashboard, review queue, issue
  detection, analytics assistant, embeddings); policies cover all of them and the next new
  query too (FR-011, SC-003). The `OR` short-circuits, so full-access users pay nothing.
- **Alternatives**: An agent filter in `calls/queries.conditions()` and every other query (misses
  the next new query); a security-barrier view per table (duplicates every read path).
- **Latency**: Not on the call hot path (the voice worker uses internal routes with no user
  context). For supervisors the predicate is an indexed `ANY` or a primary-key `EXISTS`; the
  plan measures `GET /calls` and `GET /dashboard/stats` p95 on 50,000 seeded calls before and
  after.

## R4. Role changes and removal take effect at once

- **Decision**: No token revocation. `app_resolve_subject` reads membership on every request, so
  a role change applies on the next request and a removed member gets 403 `not_a_member` at once
  (FR-009, FR-016 ask for 1 minute). The member's sign-in stays valid for their other
  workspaces, which is correct: removal is per workspace.
- **Rationale**: The per-request lookup already exists; nothing new is needed.
- **Alternatives**: Short access tokens or a revocation list per user (more moving parts for a
  guarantee the lookup already gives).

## R5. Email for invitations and ownership transfer

- **Decision**: Add `core/mailer.py` with one `Mailer` port and two implementations: `DevOutbox`
  (the existing dev outbox, used in dev and tests) and `SmtpMailer` (standard library `smtplib`
  in a worker thread, configured by `SMTP_URL` and `MAIL_FROM`), selected by `MAIL_PROVIDER`.
  Mails are sent by an arq job with 5 retries, so a mail outage never fails the invitation
  request; the team list shows "Email not sent yet" until the job succeeds.
- **Rationale**: SMTP works with any provider (SES, Postmark, Resend, Gmail) and adds no
  dependency. The spec 023 assumption "uses the sign-up email sender that exists today" is
  wrong (the app has none) and is corrected in the spec.
- **Alternatives**: A provider SDK (vendor lock and a dependency); Supabase's invite API (works
  only with Supabase, and its mail would not mention the workspace or role).

## R6. Invitation tokens and the sign-up path

- **Decision**: Invitations store `sha256(token)`; the 32-byte random token appears only in the
  link `/invite/<token>`. Preview (`GET /invitations/{token}`, no auth) returns the workspace
  name, the inviter, the roles, the masked email and the status. Accept
  (`POST /invitations/{token}/accept`) needs a signed-in user whose verified email equals the
  invited email (FR-003). For a new person: the page offers sign-up with the email filled in and
  locked; after email verification the app returns to `/invite/<token>` and accepts.
- **Bootstrap change**: `bootstrap_workspace` (run on email verification) skips creating a
  workspace when the email has a pending invitation. A user with no active membership gets 403
  `no_workspace` from `current_principal`; the web sends them to `/welcome`, which offers
  pending invitations and "Create a workspace" (`POST /workspaces`). This also covers a person
  removed from their only workspace (spec edge case).
- **Rationale**: Reuses both IdPs' sign-up unchanged; a hashed token cannot be replayed from a
  database dump.
- **Alternatives**: Magic-link accept without an account (no verified email); create the
  workspace anyway and leave it empty (trial credit granted for nothing, confusing switcher).

## R7. Audit log

- **Decision**: `team_activity` table, append-only (the app role has `INSERT` and `SELECT` only),
  RLS on `workspace_id`, kept at least 1 year. Refused requests are written by the `require()`
  dependency through an upsert keyed by (workspace, actor, 10-minute bucket) that increments a
  count and appends the permission tried (FR-020). CSV export streams the filtered rows.
- **Rationale**: One table, no new service; grouping keeps a misbehaving client from flooding it.
- **Alternatives**: Application logs only (not visible to owners); a generic audit table shared
  with 020 (020's intervention record has a different shape and lifecycle).

## R8. Concurrency and limits

- **Decision**: `workspace_members.revision`; `PATCH` needs `If-Match`, 412 on mismatch (the
  existing convention for whole-document edits, FR-019). The 50-member cap counts active members
  plus pending invitations, checked under `SELECT ... FOR UPDATE` on the workspace row. Invites
  are rate-limited to 20 per hour per workspace with the existing Redis limiter.
- **Alternatives**: A database constraint on count (not expressible without a trigger).

## R9. Supervisor assignment and routing hooks

- **Decision**: `agent_supervisors (workspace_id, agent_id, user_id, assigned_by, assigned_at)`,
  primary key `(agent_id, user_id)`, cascade on agent delete. The 002 agent create path calls
  `team.service.assign_default(agent)` (creator if supervisor, else owner, FR-013). Agent list
  and detail gain `supervisor_ids` and `has_supervisor` through 002's existing serializer.
  `team.service.recipients(agent_id)` returns assigned supervisors, or the owner plus admins who
  hold `supervisor` (FR-012); 020 calls it when it lands.
- **Removal side effects (FR-014)**: removing an assignment or a member clears the person from
  `recipients()`; 020 (not built yet) owns closing live views and handing back takeovers, and its
  plan must subscribe to the `member_removed` and `assignment_removed` events this feature
  writes to `team_activity`.

## R10. Migration of existing workspaces

- **Decision**: `s023_0001_team` creates the tables, drops the owner `UNIQUE`, adds
  `users.last_workspace_id`, inserts one active member row per workspace for its owner with
  roles `{supervisor}` (owner is derived), and assigns that owner to every existing agent.
  `app_resolve_subject` and `app_workspace_owner_verified` are replaced in the same migration.

## R11. Web

- **Decision**: Settings gains a Team tab (`/settings/team`) with Members, Invitations and
  Activity; the user menu gains a workspace switcher when the person has more than one
  workspace; new routes `/invite/:token` and `/welcome`. `useCan(permission)` reads
  `me.permissions`; navigation items and page actions use it. `api/client.ts` adds the
  `Callwright-Workspace` header from the stored current workspace and clears cached queries on a
  switch.
