# Quickstart: Workspace team and roles (023)

Validates the feature end to end on a local stack (`AUTH_PROVIDER=local`, `MAIL_PROVIDER=dev`).
Mails land in the dev outbox: `GET /v1/dev/mail`, or the API log line `[dev mail]`.

## Setup

1. `docker compose up -d` (Postgres, Redis), `uv run alembic upgrade head` in `services/api`,
   start the API, the jobs worker and the web app.
2. Sign up as `owner@example.com`, verify, and create two agents, "Billing" and "Support".
3. Confirm Settings > Team lists only you, as Owner and Supervisor, assigned to both agents
   (migration and FR-013 defaults).

## 1. Invite and join (Story 1)

1. Invite `sam@example.com` as Builder and `ana@example.com` as Analyst.
2. Open the dev outbox, copy Sam's link, open it in a private window, sign up with the locked
   email, verify, and accept. Sam lands in the owner's workspace; no second workspace or trial
   credit was created.
3. Open Ana's link while signed in as Sam: expect "This invitation is for a\*\*\*@example.com".
4. Resend Ana's invitation; the first link now shows "revoked".

## 2. Role access (Story 2, SC-002)

1. As Sam (Builder): edit and publish "Support" (works). Visit `/billing` and
   `/settings/team`: both show "You don't have access to this page. Ask an owner or admin."
   `curl -X POST /v1/team/invitations` with Sam's token returns 403 `forbidden`.
2. As Ana (Analyst): agents open read-only; calls and analytics open; publish returns 403.
3. Run the access sweep: `uv run pytest tests/integration/test_access_matrix.py` (every FR-006
   row for every role, through the API).

## 3. Supervisor scoping (Story 3, SC-003, SC-005)

1. Invite `sue@example.com` as Supervisor and assign her "Billing" only.
2. Place a browser test call on each agent (as the owner).
3. As Sue: Call History, the dashboard, CSV export and the analytics assistant show only the
   "Billing" call and its counts. Opening the "Support" call's link shows "This call belongs to
   an agent you don't supervise."
4. `team.service.recipients("Support")` returns the owner only (no supervisor assigned to it
   besides the owner); for "Billing" it returns the owner and Sue.
5. Remove every supervisor from "Support": the agent list shows "No supervisor assigned".

## 4. Change and remove (Story 4)

1. As the owner, change Sue to Supervisor and Analyst. Her next request sees all calls read-only.
2. Open the member editor in two tabs, save in one, then the other: the second gets "Changed by
   owner@example.com a moment ago".
3. Remove Sam while his tab is open: his next request returns 403 `not_a_member` and the app
   shows `/welcome` with "Create a workspace".
4. Transfer ownership to an admin (promote Ana to Admin first), typing the workspace name. Ana is
   Owner and Supervisor; the old owner is Admin and Supervisor; both got an email.

## 5. Activity (Story 5)

1. Settings > Team > Activity lists each change above once, with before and after.
2. As Ana (before promotion), hit 5 forbidden endpoints within a minute: one grouped
   `access_refused` entry with count 5.
3. Export CSV with a member filter; rows match the screen.

## 6. Latency check (research R3)

`uv run python scripts/bench_scope.py --calls 50000` seeds calls and reports p95 of
`GET /v1/calls` and `GET /v1/dashboard/stats` as Owner and as a supervisor of 3 of 20 agents.
Pass: supervisor p95 within 20% of owner p95 and under 300 ms locally.
