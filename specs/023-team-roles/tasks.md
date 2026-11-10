---
description: "Task list for 023-team-roles"
---

# Tasks: Workspace team and roles

**Input**: Design documents from `specs/023-team-roles/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/team.yaml, quickstart.md;
001 to 013 merged (newest migration `s013_0001`).

**Tests**: Required (Principle VII). Contract, access-matrix, RLS and money tests are written
first and must fail before implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US5 from spec.md

---

## Phase 1: Setup

- [ ] T001 Add `023-team-roles` to `contracts/features.txt` and run `uv run --directory services/api python ../../scripts/assemble_contracts.py` to regenerate `contracts/openapi.yaml`
- [ ] T002 [P] Add settings `MAIL_PROVIDER` (`dev` or `smtp`, default `dev`), `SMTP_URL` (secret, `smtp[s]://user:pass@host:port`), `MAIL_FROM`, `TEAM_MEMBER_LIMIT` (50), `TEAM_INVITE_TTL_DAYS` (7), `TEAM_INVITES_PER_HOUR` (20) to `services/api/app/core/config.py`
- [ ] T003 [P] Add `SMTP_URL` and `MAIL_FROM` to the API and VM secret lists in `deploy/cloudrun/deploy.sh` (`API_SECRETS`, `VM_SECRETS`, optional when `MAIL_PROVIDER=dev`) and to `deploy/vm/render-env.sh` `worker.env`; document both in `docs/OPERATIONS.md`

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: membership, roles, the access table, workspace resolution and agent scoping. Every
story needs these.

### Tests first

- [ ] T004 [P] Unit test the access table in `services/api/tests/unit/test_permissions_table.py`: every FR-006 row maps to a permission; `owner` holds every permission; `analyst` holds no write permission; `live.intervene` needs `supervisor`; `billing.read` is owner and admin, `billing.pay` owner only
- [ ] T005 [P] Route-guard architecture test in `services/api/tests/unit/test_route_guards.py`: walk `app.routes`; every `/v1` route must depend on `core.permissions.require` unless listed in `PUBLIC_ROUTES` (auth, health, `GET /invitations/{token}`, demo, public pricing), `INTERNAL_ROUTES` (`/v1/internal/*`, LiveKit and WhatsApp webhooks, Stripe webhook) or `SELF_ROUTES` (`/me`, `/me/memberships`, `/me/workspace`, `POST /workspaces`, `POST /invitations/{token}/accept`, sign-out)
- [ ] T006 [P] RLS scope test in `services/api/tests/integration/test_rls_agent_scope.py`: seed 2 agents with calls, events, analyses, annotations, evaluator runs, issues and issue samples; with `app.agent_scope` = `*`, a list of one agent, `''` and unset, assert row counts per table for all 24 tables in data-model.md; insert under a scoped context is refused for another agent's id
- [ ] T007 [P] Integration test for workspace resolution in `services/api/tests/integration/test_workspace_resolution.py`: header picks a member workspace; header for a non-member returns 403 `not_a_member`; no header uses `last_workspace_id`, then the oldest active membership; no membership returns 403 `no_workspace`; a removed member gets 403 on the next request

### Implementation

- [ ] T008 Write migration `services/api/app/migrations/versions/s023_0001_team.py` (revision `s023_0001`, down `s013_0001`): drop `UNIQUE` on `workspaces.owner_user_id`; add `users.last_workspace_id`; create `workspace_members`, `workspace_invitations`, `agent_supervisors`, `team_activity` with RLS, grants (activity: no DELETE, UPDATE only on `refused_count`, `refused_permissions`), indexes and CHECKs from data-model.md; replace `app_resolve_subject(sub, requested_workspace)` and `app_workspace_owner_verified`; add `app_invitation_by_token(hash)` `SECURITY DEFINER`; add the 24 restrictive `_agent_scope` policies from research R3; backfill owner member rows (`{supervisor}`), owner assignment to every agent and `last_workspace_id`
- [ ] T009 [P] ORM models `WorkspaceMember`, `WorkspaceInvitation`, `AgentSupervisor`, `TeamActivity` in `services/api/app/team/models.py`; add `last_workspace_id` to `User` in `services/api/app/workspaces/models.py`
- [ ] T010 [P] Implement the access table and `require(permission)` in `services/api/app/core/permissions.py`: `PERMISSIONS: dict[str, frozenset[str]]` covering every FR-006 row, `permissions_for(roles, is_owner)`, and a dependency that raises 403 problem+json `forbidden` with `detail` "Ask an owner or admin" (FR-008) and calls `team.activity.record_refusal()` (depends on T004)
- [ ] T011 Extend `services/api/app/core/auth.py`: read `Callwright-Workspace`; call the new `app_resolve_subject`; `Principal` gains `is_owner`, `roles`, `agent_scope`, `permissions`; 403 `no_workspace` and `not_a_member`; set a `contextvars.ContextVar` `agent_scope_var` (depends on T008, T010)
- [ ] T012 Extend `services/api/app/core/db.py` `set_rls_context` to `set_config('app.agent_scope', agent_scope_var.get('*'), true)` so jobs and internal routes get `*` and request transactions get the principal's scope (depends on T011)
- [ ] T013 Apply `require(...)` to every existing router (about 86 `router.py` files under `services/api/app/`) using the permission names from T010: read routes `*.read`, edit and publish routes `agents.edit`/`agents.publish`, billing `billing.read`/`billing.pay`, settings, numbers and channels `workspace.manage`, live watch `live.watch` (depends on T010; T005 passes when done)
- [ ] T014 Extend `GET /me` in `services/api/app/workspaces/router.py` and the `Me` schema in `specs/001-platform-foundation/contracts/workspaces.yaml` with `roles`, `is_owner`, `permissions` (sorted list) and `memberships_count`; update `services/api/tests/contract/test_workspaces_contract.py`
- [ ] T015 [P] Web: send `Callwright-Workspace` from the stored current workspace in `apps/web/src/api/client.ts`; on 403 `not_a_member` or `no_workspace` clear the stored workspace and route to `/welcome`
- [ ] T016 [P] Web: `useCan(permission)` in `apps/web/src/app/useCan.ts` reading `useMe().data.permissions`, with a unit test `apps/web/src/app/useCan.test.ts`
- [ ] T017 Run `pnpm gen:api` in `apps/web` to refresh `apps/web/src/api/schema.d.ts` after T014

**Checkpoint**: one-person workspaces behave exactly as before (owner holds every permission and scope `*`); T004 to T007 pass.

---

## Phase 3: User Story 1, invite people with a role (Priority: P1) MVP

**Goal**: the owner invites a colleague by email; the colleague signs up or signs in and joins with exactly those roles.
**Independent test**: quickstart section 1.

### Tests first

- [ ] T018 [P] [US1] Contract tests for `listTeamMembers`, `listTeamInvitations`, `createTeamInvitation`, `revokeTeamInvitation`, `resendTeamInvitation`, `previewInvitation`, `acceptInvitation`, `listMyMemberships`, `switchWorkspace`, `createWorkspace` in `services/api/tests/contract/test_team_contract.py`
- [ ] T019 [P] [US1] Unit tests for token generation (32 bytes, base64url 43 chars), sha256 storage, expiry and email masking in `services/api/tests/unit/test_invitation_tokens.py`
- [ ] T020 [P] [US1] Unit tests for `DevOutbox` and `SmtpMailer` (fake SMTP server via `smtplib` test double) in `services/api/tests/unit/test_mailer.py`
- [ ] T021 [P] [US1] Integration test in `services/api/tests/integration/test_invitations_flow.py`: invite, resend invalidates the old link, revoke, accept with matching verified email, `email_mismatch`, `invitation_expired`, `already_member`, `invitation_pending`, `member_limit` at 50 counting pending, 20 per hour rate limit
- [ ] T022 [P] [US1] Integration test in `services/api/tests/integration/test_bootstrap_with_invitation.py`: verifying an email that has a pending invitation creates no workspace and no trial credit; the user gets `no_workspace` until they accept
- [ ] T023 [P] [US1] Money test in `services/api/tests/integration/test_trial_credit_once.py`: `POST /workspaces` grants the trial credit only to a person's first owned workspace

### Implementation

- [ ] T024 [P] [US1] `Mailer` port, `DevOutbox` (reuse the local IdP dev outbox behind `GET /v1/dev/mail`), `SmtpMailer` and the arq job `send_mail` (5 retries, sets `workspace_invitations.mail_sent_at` on success) in `services/api/app/core/mailer.py`; register the job in `services/api/app/core/jobs.py`
- [ ] T025 [P] [US1] Invitation email body (plain text and HTML: workspace name, inviter, roles, link, expiry) in `services/api/app/team/mails.py`
- [ ] T026 [P] [US1] Pydantic schemas matching `contracts/team.yaml` in `services/api/app/team/schemas.py`
- [ ] T027 [US1] Invitation service in `services/api/app/team/invitations.py`: create (cap check under `SELECT ... FOR UPDATE` on the workspace, rate limit), resend, revoke, preview through `app_invitation_by_token`, accept (verified email match, insert or reactivate the member row, set `last_workspace_id`); each writes `team_activity`
- [ ] T028 [US1] Daily cron `expire_invitations` in `services/api/app/team/invitations.py`, registered in `services/api/app/core/jobs.py`, marking past-due pending rows `expired` and writing `invitation_expired`
- [ ] T029 [US1] Member listing and `create_workspace()` in `services/api/app/team/service.py` and `services/api/app/workspaces/service.py` (trial credit only for the first owned workspace); change `bootstrap_workspace` to skip the workspace when a pending invitation exists for the email
- [ ] T030 [US1] Router in `services/api/app/team/router.py` for the T018 operations (team routes `require("team.manage")` except `listTeamMembers` with `team.read`); mount in `services/api/app/main.py`
- [ ] T031 [P] [US1] Web hooks in `apps/web/src/api/team.ts` for members, invitations, memberships, switch and create workspace
- [ ] T032 [US1] Settings Team tab `apps/web/src/routes/settings/team/TeamTab.tsx` with Members and Invitations lists, `InviteDialog.tsx` (email, role checkboxes, used/limit counter, "Email not sent yet" state); add the tab to `apps/web/src/routes/settings/SettingsPage.tsx`, shown with `useCan("team.read")`
- [ ] T033 [P] [US1] `/invite/:token` page `apps/web/src/routes/invite/InvitePage.tsx`: preview, sign up with the email locked, sign in, accept, error states (mismatch with masked email, expired, revoked); route in `apps/web/src/router.tsx` outside `AuthGuard` for the preview
- [ ] T034 [P] [US1] `/welcome` page `apps/web/src/routes/welcome/WelcomePage.tsx`: pending invitations and "Create a workspace"
- [ ] T035 [US1] Workspace switcher in `apps/web/src/app/UserMenu.tsx` (shown with more than one membership): calls `switchWorkspace`, stores the id, clears the query cache in `apps/web/src/api/queryClient.ts`
- [ ] T036 [P] [US1] MSW handlers for team endpoints in `apps/web/src/mocks/team/handlers.ts` and unit tests `apps/web/src/routes/settings/team/TeamTab.test.tsx`, `apps/web/src/routes/invite/InvitePage.test.tsx`

**Checkpoint**: quickstart section 1 passes; a second person can join.

---

## Phase 4: User Story 2, roles decide what each person can see and do (Priority: P1)

**Goal**: the app shows only what a role allows and the server refuses the rest.
**Independent test**: quickstart section 2.

- [ ] T037 [P] [US2] Access-matrix integration test in `services/api/tests/integration/test_access_matrix.py`: one member per role (plus Builder and Supervisor combined); for every FR-006 row call one representative endpoint and assert 2xx or 403 `forbidden`; includes money rows (top-up and payment method owner-only, admin reads billing)
- [ ] T038 [P] [US2] Integration test in `services/api/tests/integration/test_role_change_effect.py`: a role change applies on the next request with the same token (FR-009)
- [ ] T039 [US2] Hide navigation items by permission in `apps/web/src/app/nav.ts` and `apps/web/src/app/Sidebar.tsx`
- [ ] T040 [US2] "No access" page `apps/web/src/app/NoAccess.tsx` ("You don't have access to this page. Ask an owner or admin.") used by route guards for Billing, Team, Settings, Channels in `apps/web/src/router.tsx`
- [ ] T041 [US2] Read-only agent editor for people without `agents.edit`: hide Save, Publish, Test call, Delete and disable inputs in the agent editor components under `apps/web/src/routes/agents/` (use `useCan`)
- [ ] T042 [P] [US2] Web tests for hidden navigation and read-only editor per role in `apps/web/src/app/shell.test.tsx` and `apps/web/src/routes/agents/AgentEditor.roles.test.tsx`

**Checkpoint**: quickstart section 2 and SC-002 pass.

---

## Phase 5: User Story 3, assign AI agents to supervisors (Priority: P1)

**Goal**: supervisors see and receive alerts only for their assigned agents.
**Independent test**: quickstart section 3.

### Tests first

- [ ] T043 [P] [US3] Contract tests for `listAgentSupervisors`, `setAgentSupervisors`, `setMemberAgents` and the agent list fields `supervisor_ids`, `has_supervisor` in `services/api/tests/contract/test_team_contract.py` and `services/api/tests/contract/test_agents_list_contract.py`
- [ ] T044 [P] [US3] Integration test in `services/api/tests/integration/test_supervisor_scope.py`: supervisor A (agents 1, 2) and B (agent 2); `/calls`, `/calls/live`, `/calls/{id}`, `/calls/export`, `/dashboard/stats`, `/review/queue`, `/issues` and the analytics assistant return only assigned agents; another agent's call returns 404 with `code` `not_your_agent` and the FR text
- [ ] T045 [P] [US3] Unit test for `recipients(agent_id)` and `assign_default(agent)` in `services/api/tests/unit/test_team_routing.py` (assigned supervisors; fallback to owner plus admins holding supervisor; creator if supervisor else owner)

### Implementation

- [ ] T046 [US3] Assignment service in `services/api/app/team/service.py`: `set_agent_supervisors`, `set_member_agents` (members must be active and hold `supervisor`, code `not_a_supervisor`), `recipients(agent_id)`, `assign_default(agent)`, `reviewers(call_id)`; writes `agent_assigned` and `agent_unassigned`
- [ ] T047 [US3] Assignment routes in `services/api/app/team/router.py` (`team.manage`; `listAgentSupervisors` with `agents.read`)
- [ ] T048 [US3] Call `team.service.assign_default()` from `create_agent` and `duplicate_agent` in `services/api/app/agents/service.py`; add `supervisor_ids` and `has_supervisor` to the agent list and detail serializers and to `specs/002-agent-builder/contracts/agents.yaml`
- [ ] T049 [US3] Map RLS-hidden call lookups to 404 `not_your_agent` (detail "This call belongs to an agent you don't supervise.") when the call exists in the workspace, via a `SECURITY DEFINER` existence check in `services/api/app/calls/read_router.py`
- [ ] T050 [P] [US3] Web: `AssignAgentsDialog.tsx` under `apps/web/src/routes/settings/team/` and a Supervisors field in agent settings under `apps/web/src/routes/agents/`; "No supervisor assigned" badge in the agent list and the publish dialog
- [ ] T051 [P] [US3] Benchmark script `scripts/bench_scope.py`: seed 50,000 calls over 20 agents, report p95 of `GET /v1/calls` and `GET /v1/dashboard/stats` as owner and as a supervisor of 3 agents (quickstart section 6)

**Checkpoint**: quickstart section 3 passes; SC-003 and SC-005 pass; benchmark within 20%.

---

## Phase 6: User Story 4, change roles, remove people, transfer ownership (Priority: P2)

**Goal**: access follows team changes at once; the owner can hand over the workspace.
**Independent test**: quickstart section 4.

- [ ] T052 [P] [US4] Contract tests for `updateTeamMember` (including 412 `member_changed`), `removeTeamMember` (409 `owner_protected`), `transferOwnership` in `services/api/tests/contract/test_team_contract.py`
- [ ] T053 [P] [US4] Integration test in `services/api/tests/integration/test_member_removal.py`: removed member's next request is 403; their assignments are deleted; their reviews and labels keep their email with `removed`; removing the last admin is allowed; owner cannot be removed or demoted by an admin
- [ ] T054 [P] [US4] Integration test in `services/api/tests/integration/test_ownership_transfer.py`: only to an admin; `name_mismatch`; old owner becomes admin and supervisor with assignments kept; both emails queued; owner cannot leave
- [ ] T055 [US4] Role change with `If-Match` revision, removal and ownership transfer in `services/api/app/team/service.py` (one transaction each; transfer updates `workspaces.owner_user_id` and both member rows); ownership email in `services/api/app/team/mails.py`
- [ ] T056 [US4] Routes `PATCH`/`DELETE /team/members/{user_id}`, `PUT /team/members/{user_id}/agents`, `POST /workspaces/current/transfer-ownership` in `services/api/app/team/router.py`
- [ ] T057 [P] [US4] Web: `MemberRolesDialog.tsx` (412 shows "Changed by <email> a moment ago" with current roles), remove confirmation, `TransferOwnershipDialog.tsx` (type the workspace name) under `apps/web/src/routes/settings/team/`; "(removed)" label where reviews and labels show an author

**Checkpoint**: quickstart section 4 passes; SC-004 passes.

---

## Phase 7: User Story 5, see who changed access (Priority: P2)

**Goal**: owners and admins can answer who gave whom access and when.
**Independent test**: quickstart section 5.

- [ ] T058 [P] [US5] Contract tests for `listTeamActivity` and `exportTeamActivity` in `services/api/tests/contract/test_team_contract.py`
- [ ] T059 [P] [US5] Integration test in `services/api/tests/integration/test_team_activity.py`: each change kind appears exactly once with before and after (SC-006); 5 refusals in 10 minutes make one grouped entry with count 5; CSV rows equal the filtered list; the app role cannot delete rows
- [ ] T060 [US5] Activity service in `services/api/app/team/activity.py`: `record()`, `record_refusal()` upsert per 10-minute bucket, filtered list, streamed CSV
- [ ] T061 [US5] Activity routes in `services/api/app/team/router.py` (`team.manage`)
- [ ] T062 [P] [US5] Web: Activity list with member, kind and date filters and Export CSV in `apps/web/src/routes/settings/team/ActivityTab.tsx`

**Checkpoint**: quickstart section 5 passes.

---

## Phase 8: Polish and cross-cutting

- [ ] T063 [P] Playwright flow in `apps/web/tests/e2e/team-invite.spec.ts`: owner invites a supervisor, the supervisor accepts in a second context, is assigned one agent and sees only that agent's call
- [ ] T064 [P] Update `docs/OPERATIONS.md` (mail settings, how to grant a role by SQL in an emergency) and `research/architecture.md` section 3 if module names changed
- [ ] T065 [P] Mark spec 001's one-user assumption done and note the 019 `reviewers()` and 020 `recipients()` hooks in `specs/019-quality-loop/spec.md` and `specs/020-live-supervision/spec.md` Assumptions
- [ ] T066 Run the full API suite, web typecheck, lint, unit tests and e2e; run `scripts/bench_scope.py`; run quickstart sections 1 to 6 and record results in `specs/023-team-roles/quickstart-results.md`
- [ ] T067 Deploy: `deploy.sh ... check-secrets build migrate api`, then the VM roll from `docs/OPERATIONS.md` section 2 (jobs worker needs the mailer and the expiry cron); set `MAIL_PROVIDER=smtp` with `SMTP_URL` and `MAIL_FROM` in Secret Manager first

---

## Dependencies

- Phase 1 then Phase 2 (T008 migration, then T011 auth, then T012 scope, then T013 route guards).
- US1 needs Phase 2. US2 needs Phase 2 and at least one invited member (US1) to test with two
  people, but its API side (T037, T038) can run once Phase 2 is done.
- US3 needs Phase 2 and the Supervisor role on a member (US1 for a second person; the owner alone
  is enough for the API tests).
- US4 needs US1 (members to change). US5 needs the activity writes added in US1, US3 and US4;
  T060 can be built early and wired as each story lands.
- Polish after all stories.

Story order: Phase 2 > US1 > {US2, US3} > US4 > US5.

## Parallel examples

- Phase 2 tests: T004, T005, T006, T007 together; then T009 and T010 together.
- US1: T018 to T023 together; then T024, T025, T026, T031, T033, T034 together.
- US3: T043, T044, T045 together; T050 and T051 alongside T046 to T049.
- US4: T052, T053, T054 together; T057 alongside T055.

## Implementation strategy

1. **MVP (Phase 2 + US1 + US2)**: invitations and enforced roles. Ship this alone: a team can
   share a workspace safely, and existing single-owner workspaces are unchanged.
2. **US3**: supervisor assignment and database scoping; unblocks 020 approval routing and 019's
   second reviewer.
3. **US4 and US5**: team changes and the activity log.
4. Each phase ends at its checkpoint with its quickstart section passing before the next starts.
