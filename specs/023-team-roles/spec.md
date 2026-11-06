# Feature Specification: Workspace team and roles (023)

**Feature Branch**: `023-team-roles`
**Created**: 2026-11-06
**Status**: Draft
**Input**: A workspace has several people with roles that grant different access. Owner (one per
workspace: billing, delete workspace, manage members; a supervisor by default). Admin (members,
settings, numbers, integrations; cannot transfer ownership). Builder (create, edit, test and
publish agents, tools, knowledge and flows; no live supervision unless also a supervisor).
Supervisor (assigned AI agents; watches their live calls, whispers, approves and takes over per
020, reviews their calls and triages their issues; several supervisors per workspace; an AI agent
can have more than one). Analyst (read-only calls, analytics and reports). Invitations by email,
role changes, removal, and an audit log of membership changes. Supervisors see only the calls of
their assigned agents unless they are an owner or admin. Replaces the 001 assumption "one user
per workspace"; 019 and 020 depend on it.

## Why

A workspace has exactly one person today. Each workspace stores a single owner, and that owner can
own only one workspace, so there is no way to invite a colleague, split building from
supervising, or keep someone away from billing. 001 lists team invitations and roles as out of
scope.

The roadmap needs a team. Live supervision (020) routes approval cards and "needs you" banners to
the people responsible for an agent, and shares work between several supervisors. Blind second
review (019) needs a second reviewer. Without a team, 019 falls back to the same person
re-reviewing a day later, and 020 Phase 3 cannot ship.

The model follows how supervised AI contact centres run: an owner who pays, admins who run the
workspace, builders who make agents, and supervisors who each look after a set of AI agents and
the calls they take.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Invite people with a role (Priority: P1)

The owner opens Settings > Team, enters a colleague's email, picks one or more roles (for
example Builder and Supervisor) and sends the invitation. The colleague gets an email, signs up or
signs in, accepts, and lands in the workspace with exactly the access those roles give.

**Why this priority**: Nothing else in this spec, 019 or 020 works until a second person can join.

**Independent Test**: Invite a new email as Analyst, accept from a second browser, and confirm the
person sees calls and analytics but every edit, publish, billing and team control is hidden and
refused if called directly.

**Acceptance Scenarios**:

1. **Given** the owner on Settings > Team, **When** they invite `sam@example.com` as Builder,
   **Then** Sam gets an email with a link valid for 7 days, and the team list shows Sam as
   "Invited" with the role, the inviter and the expiry.
2. **Given** an invitation, **When** Sam opens the link without an account, **Then** they sign up
   with that email and join the workspace in one flow; with an account, they sign in and accept.
3. **Given** an invitation, **When** someone signed in with a different email opens the link,
   **Then** it is refused with "This invitation is for s\*\*\*@example.com".
4. **Given** a pending invitation, **When** an admin revokes or resends it, **Then** the old link
   stops working at once and a resend issues a new 7-day link.
5. **Given** a person who already belongs to another workspace, **When** they accept, **Then**
   they belong to both and switch between them from the user menu.

---

### User Story 2 - Roles decide what each person can see and do (Priority: P1)

Each person holds one or more roles. The app shows only what their roles allow, and the server
refuses anything else, whatever the screen shows.

**Why this priority**: Roles are the point of the feature: a builder must not move money, and an
analyst must not change a live agent.

**Independent Test**: Sign in as each role in turn and run the access table in FR-006 against the
screens and against direct requests; every "no" must be hidden and refused.

**Acceptance Scenarios**:

1. **Given** a Builder, **When** they publish an agent version, **Then** it succeeds; **When**
   they open Billing or Team, **Then** those pages are not in the navigation and a direct visit
   shows "You don't have access to this page. Ask an owner or admin."
2. **Given** an Analyst, **When** they open an agent, **Then** it opens read-only with no Save,
   Publish, Test call or Delete controls.
3. **Given** an Admin, **When** they try to delete the workspace or transfer ownership, **Then**
   neither control is shown and a direct request is refused.
4. **Given** a person whose role is changed while they are signed in, **When** they take their
   next action, **Then** the new access applies within 1 minute without signing out.

---

### User Story 3 - Assign AI agents to supervisors (Priority: P1)

An owner or admin assigns each AI agent to one or more supervisors, from the agent's settings or
from the supervisor's row on Team. A supervisor's Live, Call History, Issues and Reviews show
only their assigned agents. Approval cards, banners and assist cards (020) go to the agent's
supervisors.

**Why this priority**: Assignment is what 020 routes on, and it keeps a supervisor's screens
focused on the calls they answer for.

**Independent Test**: With supervisors A (agents 1, 2) and B (agent 2), place calls on agents 1
and 2. Confirm A sees both calls, B sees only agent 2's call, and an approval on agent 1 goes only
to A.

**Acceptance Scenarios**:

1. **Given** an agent, **When** an admin assigns supervisors A and B, **Then** both see its calls
   and both receive its approval cards; the agent list shows their names on the agent.
2. **Given** supervisor A with agents 1 and 2, **When** A opens Call History, **Then** only calls
   of agents 1 and 2 are listed, totals and charts count only those, and a direct link to another
   agent's call shows "This call belongs to an agent you don't supervise."
3. **Given** an agent with no supervisor, **When** it goes live, **Then** the agent list and the
   publish dialog warn "No supervisor assigned", and its approvals and banners go to the owner
   and every admin who holds the Supervisor role.
4. **Given** a new workspace, **When** the owner creates agents, **Then** the owner is a
   supervisor and every new agent is assigned to the person who created it if they hold the
   Supervisor role, otherwise to the owner.
5. **Given** a supervisor whose assignment is removed during a live call they are watching,
   **When** the removal saves, **Then** their live view closes within 10 seconds, and a takeover
   they hold is handed back to the agent first (020 Story 6).

---

### User Story 4 - Change roles, remove people and transfer ownership (Priority: P2)

Owners and admins change a member's roles or remove them. Removal ends the person's access at
once. The owner can hand the workspace to an admin.

**Why this priority**: Teams change; access must follow the same day.

**Independent Test**: Remove a supervisor who has a session open and a pending approval; confirm
the session is refused within 1 minute and the approval moves to the agent's other supervisors.

**Acceptance Scenarios**:

1. **Given** a member, **When** an admin removes them, **Then** all their sessions stop working
   within 1 minute, their pending approval cards go to the agent's remaining supervisors, and
   their past actions (reviews, whispers, approvals, edits) keep their name with "(removed)".
2. **Given** an admin, **When** they try to remove the owner or change the owner's roles,
   **Then** it is refused. Removing the last admin is allowed, because the owner remains.
3. **Given** the owner, **When** they transfer ownership to an admin and type the workspace name
   to confirm, **Then** the admin becomes owner, the old owner becomes Admin and Supervisor, and
   both get an email.
4. **Given** the owner, **When** they try to leave the workspace, **Then** they are told to
   transfer ownership first.

---

### User Story 5 - See who changed access (Priority: P2)

Settings > Team > Activity lists every membership change: invitations sent, accepted, revoked
or expired, role changes, removals, agent assignments, ownership transfers and refused access
attempts, with who, whom, what changed and when.

**Why this priority**: Owners must be able to answer "who gave this person access, and when?".

**Independent Test**: Make one change of each kind and confirm each appears once with actor,
subject, before and after values and time, and that the CSV export matches the screen.

**Acceptance Scenarios**:

1. **Given** a role change from Analyst to Builder, **When** Activity opens, **Then** it shows the
   actor, the member, "Analyst → Builder" and the time.
2. **Given** 5 refused requests from one member within 10 minutes, **When** Activity opens,
   **Then** they appear as one grouped entry with the count and the pages or actions tried.
3. **Given** Activity filtered by member and date range, **When** the admin exports, **Then** a
   CSV with the same rows downloads.

---

### Edge Cases

- An invitation to an email that is already a member: refused with "Already in this workspace".
- Two admins change the same member's roles at the same time: the second save is refused with
  "Changed by <name> a moment ago" and shows the current roles.
- A member with no role left after an edit: not allowed; at least one role is required.
- A supervisor assigned to an agent that is deleted: the assignment goes with the agent; the
  supervisor's past calls of that agent stay visible to them read-only.
- A builder who is not a supervisor places a test call: they see that test call and its
  transcript; test calls never route approvals to supervisors, they show on the test page.
- The only supervisor of an agent is removed: the agent falls back to owner and admins (Story 3,
  scenario 3) and shows the "No supervisor assigned" warning.
- An invitation expires while the invitee is filling in sign-up: the account is created, joining
  is refused with "This invitation expired, ask for a new one", and Activity records the expiry.
- A workspace reaches 50 members: further invitations are refused with the limit shown.
- A person removed from their only workspace signs in: they see a page to create a new workspace,
  not the old one.
- Workspace API keys and outbound call requests act as the workspace, not as a member; only owner
  and admins can create or revoke keys.

## Requirements *(mandatory)*

### Functional Requirements

Membership
- **FR-001**: A workspace MUST have exactly one owner and MAY have up to 50 members in total,
  counting pending invitations.
- **FR-002**: A person MUST be able to belong to several workspaces and switch between them from
  the user menu; each workspace's data MUST stay separate exactly as today.
- **FR-003**: Owners and admins MUST be able to invite by email with one or more roles. An
  invitation MUST be single-use, valid for 7 days, bound to that email, and revocable and
  resendable; resending MUST invalidate the previous link.
- **FR-004**: Every member MUST hold at least one role. Roles MUST combine as the union of their
  access.

Roles and access
- **FR-005**: The roles MUST be Owner, Admin, Builder, Supervisor and Analyst. The owner MUST
  always hold Owner and Supervisor; the Supervisor role MAY be added to any other member.
- **FR-006**: Access MUST follow this table (Y = yes, A = only for assigned agents, R = read
  only, - = no):

  | Area | Owner | Admin | Builder | Supervisor | Analyst |
  |---|---|---|---|---|---|
  | Billing: add funds, payment method, invoices | Y | R | - | - | - |
  | Delete workspace, transfer ownership | Y | - | - | - | - |
  | Team: invite, change roles, remove, assign agents | Y | Y | - | - | - |
  | Workspace settings, phone numbers, channels, API keys, integrations | Y | Y | - | - | - |
  | Agents, flows, tools, knowledge: create, edit, test, publish, roll back | Y | Y | Y | R (A) | R |
  | Test calls and simulations | Y | Y | Y | A | - |
  | Live calls: watch | Y | Y | - | A | - |
  | Live calls: whisper, approve, listen, take over (020) | if Supervisor | if Supervisor | - | A | - |
  | Call history, transcripts, recordings | Y | Y | Y | A | R |
  | Reviews and label overrides (019) | Y | Y | Y | A | - |
  | Issues: triage, apply fixes (009) | Y | Y | Y | A (triage only) | R |
  | Analytics and reports (006, 021) | Y | Y | Y | A | R |
  | Team activity log | Y | Y | - | - | - |

- **FR-007**: The server MUST enforce FR-006 on every request, including exports, links shared
  by URL and live updates; hiding a control in the app MUST NOT be the only check.
- **FR-008**: A refused request MUST return a clear "no access" message naming who can grant it
  (owner or admins), and MUST be recorded per FR-020.
- **FR-009**: A role change or removal MUST take effect on the member's next request and no later
  than 1 minute after saving, without the member signing out.

Supervisor assignment
- **FR-010**: Owners and admins MUST be able to assign each agent to any number of members who
  hold the Supervisor role, from the agent and from the member's Team row.
- **FR-011**: For a member whose only call access is Supervisor, every list, count, chart,
  export, search and live update of calls, reviews, issues and analytics MUST include only
  their assigned agents.
- **FR-012**: Approval cards, "needs you" banners, assist cards and live-check alerts (020) MUST
  go to the agent's assigned supervisors. An agent with no assigned supervisor MUST route them to
  the owner and every admin holding Supervisor, and MUST show "No supervisor assigned" on the
  agent list and in the publish dialog.
- **FR-013**: A new agent MUST be assigned to its creator when the creator holds Supervisor,
  otherwise to the owner.
- **FR-014**: Removing an assignment or a member MUST, within 10 seconds, close their live views
  of the affected calls, hand back any takeover they hold, and move their pending approval cards
  to the remaining recipients under FR-012.

Changes and ownership
- **FR-015**: Owners and admins MUST be able to change roles and remove members; nobody but the
  owner MAY change the owner's roles, and the owner MUST NOT be removable.
- **FR-016**: Removing a member MUST end all their sessions within 1 minute and keep their name,
  marked "(removed)", on everything they did.
- **FR-017**: The owner MUST be able to transfer ownership only to an existing admin, after typing
  the workspace name. The former owner MUST become Admin and Supervisor, keep their assignments,
  and both people MUST be emailed.
- **FR-018**: The owner MUST NOT be able to leave the workspace without transferring ownership.
- **FR-019**: Concurrent edits to the same member MUST be detected; the later save is refused and
  shows the current state.

Audit
- **FR-020**: The workspace MUST record invitations (sent, accepted, revoked, expired), role
  changes with before and after, removals, agent assignments and unassignments, ownership
  transfers and refused requests, each with actor, subject, details and time. Refused requests
  from one member MUST be grouped per 10 minutes.
- **FR-021**: Owners and admins MUST be able to filter the activity log by member, kind and date
  range and export it as CSV. Entries MUST be kept for at least 1 year and MUST NOT be editable.

Dependent specs
- **FR-022**: This spec replaces the 001 assumption "one user per workspace". 019 FR-017's
  single-member path MUST apply when the call has only one person able to review it under
  FR-006. 020 Story 7 work states and approval routing MUST use the assigned supervisors of
  FR-012.

### Key Entities

- **Membership**: a person in a workspace; roles, status (active, removed), joined and removed
  times, who invited them.
- **Invitation**: email, roles, inviter, created, expires, status (pending, accepted, revoked,
  expired).
- **Role**: one of Owner, Admin, Builder, Supervisor, Analyst; fixed set, access per FR-006.
- **Supervisor assignment**: agent, member, assigned by, assigned at.
- **Team activity entry**: kind, actor, subject, before and after values, time; append-only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An owner invites a colleague and the colleague is working in the workspace in under
  3 minutes, including sign-up.
- **SC-002**: In an automated access test that runs every row of FR-006 for every role, both
  through the app and through direct requests, 100% of "no" cases are refused and 100% of "yes"
  cases succeed.
- **SC-003**: In tests, a supervisor sees zero calls, counts or exports from agents they are not
  assigned to.
- **SC-004**: A removed member's next request is refused within 1 minute in 100% of test runs.
- **SC-005**: 100% of approval cards in tests reach only the agent's assigned supervisors, or the
  owner and supervising admins when none is assigned.
- **SC-006**: Every membership change made in tests appears exactly once in the activity log.

## Assumptions

- Roles are a fixed set; custom roles and per-permission editing are out of scope.
- Supervisor access is scoped by agent, not by phone number, team or queue.
- Builders see all calls because they need them to fix agents. Keeping builders away from caller
  data is out of scope.
- Analysts see transcripts and recordings read-only; hiding caller data from analysts would come
  with 017's masking settings.
- Admins can read billing (balance, usage, invoices) but only the owner pays or changes payment.
- No per-seat price in this version; the 50-member cap is a safety limit, adjustable per
  workspace by Callwright staff.
- Invitation and ownership emails use the sign-up email sender that exists today.
- Existing workspaces migrate with their current user as Owner and Supervisor, assigned to every
  existing agent.
- Callwright staff accounts (platform admin) keep their current support access, outside these
  roles.
