# Implementation Plan: Workspace team and roles

**Branch**: `023-team-roles` | **Date**: 2026-11-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/023-team-roles/spec.md`

## Summary

Turn the one-owner workspace into a team. A new `team` API module owns members, invitations,
supervisor assignments and the team activity log. The owner stays in `workspaces.owner_user_id`;
every person, owner included, has a `workspace_members` row with roles from `admin`, `builder`,
`supervisor`, `analyst`. `app_resolve_subject` now picks the workspace from a
`Callwright-Workspace` header (or the last one used) and returns the person's roles and agent
scope on every request, so role changes and removals apply on the next request with no token
revocation. One access table in `core/permissions.py` drives a `require(permission)` route
dependency and the permission list the web uses to hide controls. Supervisors are scoped at the
database layer: a new `app.agent_scope` setting and restrictive RLS policies on 24 call and agent
tables, so every existing read path (list, live, detail, export, dashboard, review queue,
issues, analytics assistant) shows only assigned agents without per-query changes. Invitations
are hashed single-use 7-day links sent by a new SMTP mailer through an arq job. 020 and 019 use
the routing function `team.service.recipients()` and the member count this feature provides.

## Technical Context

**Language/Version**: Python 3.12 (API); TypeScript 5 (web). No voice worker change.
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, the existing Redis
rate limiter; standard library `smtplib`, `secrets`, `hashlib`, `contextvars`. Web: TanStack
Query, React Router, Radix dialogs and tabs. No new dependency.
**Storage**: PostgreSQL 16 with RLS: new `workspace_members`, `workspace_invitations`,
`agent_supervisors`, `team_activity`; `users.last_workspace_id`; `workspaces.owner_user_id` loses
`UNIQUE`; restrictive `_agent_scope` policies on 24 existing tables (research R3).
**Testing**: pytest contract tests for `team.yaml`; an access-matrix integration test that runs
every FR-006 row for every role; an RLS scope test per scoped table; a route-guard architecture
test; web unit tests for `useCan` and the Team page; one Playwright flow (invite, accept,
supervisor sees only their agent).
**Target Platform**: Cloud Run (API), the realtime VM (jobs worker), Vercel (web).
**Project Type**: Web service + SPA.
**Performance Goals**: `app_resolve_subject` stays one round trip (adds one indexed join and one
aggregate of assigned agent ids); supervisor p95 on `GET /calls` and `GET /dashboard/stats`
within 20% of owner p95 on 50,000 seeded calls; invitation request under 300 ms p95 (mail is
async); role change effective on the next request (spec asks 1 minute).
**Constraints**: Server enforcement on every route (FR-007); no cross-tenant read except the
narrow `SECURITY DEFINER` invitation lookup; jobs and internal worker routes keep full access
inside their workspace; forward-only migration with data backfill; house style (no em dashes).
**Scale/Scope**: up to 50 members and a few hundred agents per workspace; 1 new API module, 1
core module (`permissions.py`) and 1 core mailer; 3 new web routes and a Settings tab.

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design.*

| Gate | Principle | How this plan satisfies it | Status |
|---|---|---|---|
| Vendor behind adapter | I | No speech vendor touched. Email sits behind one `Mailer` port (`core/mailer.py`) with a dev outbox and an SMTP adapter selected by `MAIL_PROVIDER`; SMTP works with any provider. | Pass |
| Latency impact stated | II | Not on the turn path: the voice worker and `/v1/internal/*` routes are unchanged and run without user context (scope `*`). Per-request auth adds one indexed join; supervisor reads add an indexed `ANY` or primary-key `EXISTS`, measured by `scripts/bench_scope.py` (quickstart step 6). | Pass |
| Metering impact stated | III | No new meters or charges. Billing pay actions become owner-only (`billing.pay`); the ledger is untouched. `POST /workspaces` grants trial credit only to a person's first owned workspace (money test T-M1), so new workspaces cannot farm credit. | Pass |
| Measurability path | IV | SC-002 to SC-006 each map to a test: access matrix, RLS scope test, removal test, recipients test, activity-once test. Removed members keep their name on reviews and labels, so calibration (007) keeps its history. | Pass |
| Tenancy and privacy | V | RLS on all new tables; supervisor scoping is enforced by restrictive RLS policies, not only API code (R3), and fails closed when the setting is missing. The only pre-tenant read is `app_invitation_by_token`, returning masked email and no other rows. Tokens are stored hashed. Activity log is append-only by grants. | Pass |
| Complexity justified | VI | No new service or queue; one module, one table per entity. Deviations listed below. | Pass |
| Contract and money tests | VII | `team.yaml` contract tests written first; 001's `Me` schema gains `roles`, `is_owner`, `permissions` and `memberships_count` with its contract test updated; money tests: owner-only top-up and payment method, admin read-only billing, trial credit once per person. | Pass |

Post-design re-check: Pass. The design adds no service and keeps every new read inside RLS.

## Project Structure

### Documentation (this feature)

```text
specs/023-team-roles/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/team.yaml
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
services/api/app/
├── core/
│   ├── auth.py               # EXTEND: Principal gains is_owner, roles, agent_scope, permissions;
│   │                         #   reads Callwright-Workspace; 403 no_workspace / not_a_member
│   ├── db.py                 # EXTEND: set_rls_context also sets app.agent_scope from the request context var
│   ├── permissions.py        # NEW: access table (FR-006), require(permission), refused-request logging
│   └── mailer.py             # NEW: Mailer port, DevOutbox, SmtpMailer; send job
├── team/
│   ├── models.py  schemas.py  router.py
│   ├── service.py            # members, roles, removal, ownership transfer, recipients(), assign_default()
│   ├── invitations.py        # create, resend, revoke, preview, accept, expiry job
│   ├── activity.py           # append entries, grouped access_refused upsert, CSV export
│   └── mails.py              # invitation and ownership email bodies (plain text and HTML)
├── workspaces/
│   ├── service.py            # EXTEND: bootstrap skips workspace when an invitation is pending; create_workspace()
│   └── router.py             # EXTEND: GET /me returns roles, is_owner, permissions
├── agents/service.py         # EXTEND: on create call team.service.assign_default(); list adds supervisor_ids, has_supervisor
├── billing/router.py  pricing/router.py  ...   # EXTEND: each router's endpoints use require(...)
└── migrations/versions/s023_0001_team.py

services/api/tests/
├── contract/test_team_contract.py
├── unit/test_permissions_table.py  test_invitation_tokens.py  test_mailer.py
├── integration/test_access_matrix.py  test_rls_agent_scope.py  test_invitations_flow.py
│               test_member_removal.py  test_ownership_transfer.py  test_team_activity.py
│               test_bootstrap_with_invitation.py  test_trial_credit_once.py
└── unit/test_route_guards.py          # every /v1 route declares require() or is allowlisted

scripts/bench_scope.py                  # NEW: seed calls, compare owner vs supervisor p95

apps/web/src/
├── api/client.ts             # EXTEND: Callwright-Workspace header, clear cache on switch
├── api/team.ts               # NEW: hooks for members, invitations, assignments, activity
├── app/useCan.ts             # NEW: permission check from me.permissions
├── app/UserMenu.tsx          # EXTEND: workspace switcher
├── app/Nav*.tsx              # EXTEND: hide items the person cannot use
├── routes/settings/team/     # NEW: TeamTab (Members, Invitations, Activity), InviteDialog,
│                             #   MemberRolesDialog, AssignAgentsDialog, TransferOwnershipDialog
├── routes/invite/InvitePage.tsx      # NEW: /invite/:token
├── routes/welcome/WelcomePage.tsx    # NEW: /welcome (pending invitations, create a workspace)
└── routes/agents/...         # EXTEND: supervisors field in agent settings, "No supervisor assigned" badge
```

**Structure Decision**: One new module `team` (research/architecture.md section 3 gains a 023
row: API `team`, web `/settings/team`, `/invite/:token`, `/welcome`). Cross-owner edits, listed
again in tasks: 001 `core/auth.py`, `core/db.py`, `workspaces/*` and the `Me` contract; 002
`agents/service.py` and the agent list contract (`supervisor_ids`, `has_supervisor`); every
router gains `require(...)` (mechanical, guarded by the route-guard test); 001's shell
navigation and user menu.

### Request flow

1. Web sends `Authorization` and `Callwright-Workspace`.
2. `current_principal` verifies the token, calls `app_resolve_subject(sub, header)`, gets user,
   workspace, owner flag, roles and agent scope, derives permissions, and stores the scope in a
   context variable.
3. The route's `require(permission)` checks the permission; on refusal it writes the grouped
   `access_refused` entry and returns 403 problem+json.
4. `db.transaction(...)` sets `app.workspace_id`, `app.user_id` and `app.agent_scope`; RLS does
   the tenant and agent filtering.

### Hooks for dependent specs

- 020: `team.service.recipients(agent_id) -> list[user_id]` (assigned supervisors, else owner
  plus admins holding supervisor, FR-012); `team_activity` kinds `member_removed` and
  `agent_unassigned` for closing live views and handing back takeovers (FR-014). 020's plan owns
  that behaviour.
- 019: `team.service.reviewers(call_id) -> int` (members allowed to review the call) for FR-017's
  same-reviewer rule.

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Restrictive RLS policies on 24 existing tables | FR-011 and SC-003 require supervisors to see only their agents everywhere, and constitution V requires database-level isolation | Filtering in each query misses at least 8 direct readers today and every future one |
| Request context variable for `app.agent_scope` | Every router already calls `db.transaction(workspace_id, user_id)`; a context variable applies the scope without editing 40+ call sites, and jobs keep `*` | Passing the principal to every transaction touches every router and is easy to forget |
| `Callwright-Workspace` request header | A person can belong to several workspaces (FR-002) while the IdP token stays workspace-agnostic | A workspace claim in the JWT needs IdP hooks and a refresh on every switch |
| `core/mailer.py` with an SMTP adapter and an arq job | The app sends no email today; invitations and transfers must (FR-003, FR-017) | A provider SDK adds a dependency and a vendor; sending inline fails requests during mail outages |
| `SECURITY DEFINER` function `app_invitation_by_token` | The invitation preview and accept run before the person has a workspace context | Disabling RLS for the invitations table exposes every workspace's invitations |
| New ID prefix `inv_` | Invitations are addressable resources (revoke, resend) | Using the email as key puts personal data in URLs and logs |
