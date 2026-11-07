# Data model: Workspace team and roles (023)

Migration `s023_0001_team` (down revision `s013_0001`, or the newest at implementation time).
Forward-only. All new tables have `ENABLE` and `FORCE ROW LEVEL SECURITY` with a
`<table>_tenant` policy on `app.workspace_id`, and column grants to `callwright_app`.

## Changed tables

### `workspaces` (001)

| Column | Change |
|---|---|
| `owner_user_id` | Drop `UNIQUE` (a person may own several workspaces). Stays `NOT NULL`; it is the only record of who the owner is. |

### `users` (001)

| Column | Type | Notes |
|---|---|---|
| `last_workspace_id` | `text NULL` | Workspace used when a request has no `Callwright-Workspace` header (research R1). Not a foreign key that blocks workspace deletion: set to null on delete. |

## New tables

### `workspace_members`

| Column | Type | Notes |
|---|---|---|
| `workspace_id` | `text NOT NULL` | FK `workspaces`, cascade |
| `user_id` | `text NOT NULL` | FK `users` |
| `roles` | `text[] NOT NULL` | Subset of `admin`, `builder`, `supervisor`, `analyst`; CHECK non-empty and every element in the set. The owner's row always contains `supervisor` (service check plus CHECK via `app_member_roles_ok()` that reads `workspaces.owner_user_id`). |
| `status` | `text NOT NULL` | `active` or `removed` |
| `invited_by` | `text NULL` | user id; null for the owner's own row |
| `joined_at` | `timestamptz NOT NULL` | |
| `removed_at` | `timestamptz NULL` | set with `status = removed` |
| `removed_by` | `text NULL` | |
| `revision` | `int NOT NULL DEFAULT 1` | incremented on every change; `If-Match` (FR-019) |

Primary key `(workspace_id, user_id)`. Index `(user_id) WHERE status = 'active'` for
`app_resolve_subject`. A removed member who is invited again gets the same row back with
`status = active` and new roles; the old removal stays in `team_activity`.

**Rules**
- Owner: `workspaces.owner_user_id = user_id`. Cannot be removed; only the owner can change
  their own roles, and `supervisor` cannot be dropped (FR-005, FR-015).
- Effective roles = `roles` plus `owner` when the user is the owner.
- At most 50 rows with `status = active` plus pending invitations per workspace (FR-001).

**State**: `active` → `removed` (by owner or admin) → `active` (accepted a new invitation).

### `workspace_invitations`

| Column | Type | Notes |
|---|---|---|
| `id` | `text PK` | prefix `inv_` |
| `workspace_id` | `text NOT NULL` | |
| `email` | `citext NOT NULL` | lower-cased |
| `roles` | `text[] NOT NULL` | same CHECK as members |
| `token_hash` | `bytea NOT NULL UNIQUE` | sha256 of the 32-byte token; the token is only in the link |
| `status` | `text NOT NULL` | `pending`, `accepted`, `revoked`, `expired` |
| `invited_by` | `text NOT NULL` | |
| `created_at` | `timestamptz NOT NULL` | |
| `expires_at` | `timestamptz NOT NULL` | `created_at + 7 days` |
| `accepted_by` | `text NULL` | user id |
| `responded_at` | `timestamptz NULL` | accepted, revoked or expired time |
| `mail_sent_at` | `timestamptz NULL` | set by the mail job; null shows "Email not sent yet" |

Partial unique index `(workspace_id, email) WHERE status = 'pending'`: one live invitation per
email. Resend marks the old row `revoked` and inserts a new one in one transaction (FR-003).
A daily job marks `pending` rows past `expires_at` as `expired` and writes `team_activity`;
accept also checks the time, so the job is only for the log.

**State**: `pending` → `accepted` | `revoked` | `expired`.

The public preview and accept look invitations up by `token_hash` before any workspace context
exists, through a `SECURITY DEFINER` function `app_invitation_by_token(hash)` that returns only
id, workspace name, inviter email, roles, masked email, status and expiry (no other rows).

### `agent_supervisors`

| Column | Type | Notes |
|---|---|---|
| `workspace_id` | `text NOT NULL` | |
| `agent_id` | `text NOT NULL` | FK `agents`, cascade on delete |
| `user_id` | `text NOT NULL` | must be an active member holding `supervisor` (service check) |
| `assigned_by` | `text NOT NULL` | |
| `assigned_at` | `timestamptz NOT NULL` | |

Primary key `(agent_id, user_id)`; index `(workspace_id, user_id)` for computing a supervisor's
scope. Removing the `supervisor` role or the member deletes their rows in the same transaction.

### `team_activity`

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint identity PK` | local id |
| `workspace_id` | `text NOT NULL` | |
| `kind` | `text NOT NULL` | `invitation_sent`, `invitation_accepted`, `invitation_revoked`, `invitation_expired`, `roles_changed`, `member_removed`, `agent_assigned`, `agent_unassigned`, `ownership_transferred`, `access_refused` |
| `actor_user_id` | `text NULL` | null for system (expiry job) |
| `subject_user_id` | `text NULL` | member affected |
| `subject_email` | `text NULL` | for invitations |
| `agent_id` | `text NULL` | for assignments |
| `before` | `jsonb NULL` | e.g. `{"roles": ["analyst"]}` |
| `after` | `jsonb NULL` | |
| `refused_count` | `int NULL` | `access_refused` only |
| `refused_permissions` | `text[] NULL` | `access_refused` only, distinct permission names tried |
| `bucket_start` | `timestamptz NULL` | `access_refused` only; 10-minute bucket |
| `created_at` | `timestamptz NOT NULL` | |

Grants: `INSERT`, `SELECT` and (for the `access_refused` upsert only) `UPDATE` of
`refused_count`, `refused_permissions`; no `DELETE`. Unique index
`(workspace_id, actor_user_id, bucket_start) WHERE kind = 'access_refused'` for the grouping
upsert (FR-020). Index `(workspace_id, created_at desc)`. Rows kept at least 1 year; no purge in
this feature.

## Functions replaced

- `app_resolve_subject(sub text, requested_workspace text)`: returns `user_id`, `email`,
  `email_verified`, `is_admin`, `workspace_id`, `is_owner`, `roles`, `scope`. Picks the requested
  workspace if the user is an active member, else `last_workspace_id` if still active, else the
  oldest active membership; returns a null workspace when there is none (API answers 403
  `no_workspace`). `scope` is `*` or the comma list of the user's assigned agent ids (research
  R3).
- `app_workspace_owner_verified`: unchanged meaning, now reads `workspaces.owner_user_id` without
  relying on its uniqueness.

## RLS additions on existing tables

Restrictive `<table>_agent_scope` policies as listed in research R3 (14 tables by `agent_id`,
10 by `call_id`).

## Data migration

1. For each workspace: insert `workspace_members (workspace_id, owner_user_id, {supervisor},
   active, joined_at = workspaces.created_at)`.
2. For each agent: insert `agent_supervisors (agent_id, owner_user_id, assigned_by = owner)`.
3. `users.last_workspace_id = ` the workspace they own.

## Principal (API, not stored)

`Principal` gains `is_owner: bool`, `roles: frozenset[str]` (effective, including `owner`),
`agent_scope: str` (`*` or comma list) and `permissions: frozenset[str]` derived from
`core/permissions.py`.
