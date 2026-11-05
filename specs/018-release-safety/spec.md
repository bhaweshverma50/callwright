# Feature Specification: Release safety (018)

**Feature Branch**: `018-release-safety`
**Created**: 2026-11-05
**Status**: Draft
**Input**: Make putting an agent version live safe and reversible. A version publishes only after
its release tests pass (with a logged owner override). Tests run several times so flaky cases
show up. Rollback reaches new calls within a minute. An emergency stop pauses an agent without
cutting live calls. Each phone number can pin a version or be switched off. A "Needs attention"
view lists broken configuration already in use. A daily spend cap with a warning level protects
the workspace's balance.

## Why

Callwright already records every save as a version, publishes any version without publish
blockers, restores old versions and lets calls in progress finish on the version they started
with (002). The gaps are on the way out:

- Publishing checks configuration (blockers such as retired components) but not behaviour. An
  agent's test cases (008) are run by hand, if at all, and a version whose tests fail can still go
  live.
- Each test case runs once. An answer that passes two times out of three looks green.
- Getting back to the previous version means finding it in history and publishing it again.
  Unpublishing refuses every new call because the agent then has no published version.
- A phone number names an inbound agent and an outbound agent and always follows that agent's
  published version. It cannot stay on a known-good version while the agent changes, and it has
  no on/off switch apart from deleting it (which drains it).
- The agents list has an "attention" tab, but it only means "the draft has publish blockers".
  Problems in configuration that is already serving calls, such as a deleted tool, a failed
  document or a number pointing at an unpublished agent, are not collected anywhere.
- Spending stops only when the prepaid balance runs out (001). Nothing limits how much a
  runaway day can spend.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A version can't go live until its tests pass (Priority: P1)

Each agent has a **release test set**: its test cases marked "release" (by default, all of them).
When the operator publishes a version, the platform runs the release test set against that exact
version. If it already has a fresh passing run, it publishes at once. Otherwise it offers "Run
tests and publish if they pass". A version whose run does not pass cannot be published. The
workspace owner can publish it anyway by giving a reason. That override is recorded on the
version and in the audit history.

**Why this priority**: This is the main protection against shipping a regression to real callers.
It uses the test cases operators already write.

**Independent Test**: Give an agent 5 release test cases. Save a version that breaks one. Click
Publish and confirm the run starts, the failure is shown and the version is not published. Override
with a reason and confirm the version goes live with an "override" badge and an audit entry.

**Acceptance Scenarios**:

1. **Given** a version with no run yet, **When** the operator clicks Publish, **Then** they are
   offered "Run tests and publish if they pass", with the number of cases, runs and estimated
   cost.
2. **Given** the run passes, **When** it finishes, **Then** the version is published, and the
   operator is told how many cases passed.
3. **Given** the run fails, **When** it finishes, **Then** the version is not published, the
   failing and flaky cases are listed with the agent's replies, and the published version is
   unchanged.
4. **Given** a failed run, **When** the owner chooses "Publish anyway", **Then** a reason of at
   least 10 characters is required. The version is published, and the override (who, when, which
   cases failed, reason) is shown on the version and in the audit history.
5. **Given** a passing run on version 7, **When** the operator saves version 8, **Then** version 8
   has no passing run, and publishing it starts a new run.
6. **Given** the gate is switched off for an agent, **When** the operator publishes, **Then** the
   version publishes without a run, and the version shows "Published without release tests".
7. **Given** an agent with no release test cases, **When** the operator publishes, **Then** it
   publishes with a warning that the agent has no release tests, and the agent is listed in Needs
   attention.

---

### User Story 2 - Roll back or stop an agent in one click (Priority: P1)

From the agent's header, the operator can **roll back** to the previously published version with
one click and a confirmation. New calls use it within 60 seconds. If something worse is happening,
they can **pause** the agent. New calls (inbound, outbound and due callbacks) are refused or sent
to a fallback number, while calls in progress carry on. Resume reverses it.

**Why this priority**: When a bad version is live, minutes matter, and the fix must not drop
callers who are mid-conversation.

**Independent Test**: Publish version 2 over version 1. Start a long call. Roll back and confirm a
new call 60 seconds later runs version 1 while the first call stays on version 2. Then pause and
confirm the live call continues, and that a new inbound call hears the paused message or reaches
the fallback number.

**Acceptance Scenarios**:

1. **Given** version 3 is published and version 2 was published before it, **When** the operator
   clicks "Roll back to version 2" and confirms, **Then** version 2 is published, and every new
   call that starts 60 seconds or more after the click uses version 2.
2. **Given** a rollback, **When** it happens, **Then** it does not run the release tests (the
   version was live before), and the history records "rolled back from 3 to 2" with who and when.
3. **Given** a live call on version 3, **When** the agent is rolled back or paused, **Then** that
   call continues to its end on version 3.
4. **Given** a paused agent with a fallback number, **When** an inbound call arrives, **Then** it
   is transferred to the fallback number without the agent answering.
5. **Given** a paused agent without a fallback number, **When** an inbound call arrives, **Then**
   the caller hears the paused message ("Sorry, we can't take your call right now. Please try
   again later.") and the call ends. The call is recorded as refused with reason "agent paused".
6. **Given** a paused agent, **When** an outbound call or callback is due, **Then**
   it is not placed. Callbacks wait and fail as missed after their window (011).
7. **Given** a paused agent, **When** the operator resumes it, **Then** new calls are accepted
   again within 60 seconds on the published version.

---

### User Story 3 - Repeat runs show flaky cases (Priority: P1)

Every test case in a release run is run k times (default 3). It passes only if all k runs pass.
A case that passes some runs but not all is marked **flaky**. Operators can also choose k for
ordinary test runs (008).

**Why this priority**: Voice agents are not deterministic. A single green run hides cases that
fail one call in three, and that is exactly what callers meet.

**Independent Test**: Write a case the agent passes about half the time. Run it with k = 3 and
confirm it is shown as flaky with 1 or 2 of 3 passing. Run a stable case and confirm it shows
3 of 3.

**Acceptance Scenarios**:

1. **Given** k = 3, **When** a case passes 3 of 3, **Then** it is "passed". With 0 of 3 it is
   "failed". With 1 or 2 of 3 it is "flaky", and the count is shown.
2. **Given** the default gate settings, **When** a release run has a flaky case, **Then** the run
   does not pass.
3. **Given** a case flagged flaky in 2 of its last 5 release runs, **When** the operator opens it,
   **Then** the history of its outcomes is shown so they can fix the case or the agent.
4. **Given** a manual override of one run's verdict (008), **When** the case's result is counted,
   **Then** the overridden verdict is used for that run.
5. **Given** k = 3, **When** the run is estimated, **Then** the cost shown is three times the
   single-run cost.

---

### User Story 4 - Pin a version per number and switch numbers off (Priority: P2)

On the Phone numbers page, each number's inbound agent can follow **latest published** (today's
behaviour and the default) or be **pinned** to a specific published version. Each number also has
an **enabled** switch. A disabled number refuses new calls, or sends them to the fallback number,
without cutting calls in progress.

**Why this priority**: Operators with several lines want to try a new version on one line while
the others stay on the known-good one, and to take one line out of service without touching the
agent.

**Independent Test**: Pin number A to version 4 and leave number B on latest. Publish version 5.
Confirm calls to A run 4 and calls to B run 5. Disable A during a live call and confirm the live
call continues and the next call to A is refused.

**Acceptance Scenarios**:

1. **Given** number A pinned to version 4, **When** version 5 is published or the agent is rolled
   back, **Then** calls to A still use version 4.
2. **Given** a pinned number, **When** the agent's published version changes, **Then** the number
   shows "Pinned to version 4 (latest is 5)".
3. **Given** number A is disabled, **When** a call arrives, **Then** it is refused, or sent to the
   number's fallback if one is set, and recorded with reason "number disabled".
4. **Given** number A is disabled, **When** an outbound call or callback is requested from it,
   **Then** it is refused with "number disabled".
5. **Given** a pinned version, **When** the operator tries to delete the agent, **Then** they are
   told which numbers pin its versions.
6. **Given** an agent that is paused, **When** a call reaches a number pinned to it, **Then** the
   pause still applies.

---

### User Story 5 - See configuration that needs attention (Priority: P2)

A **Needs attention** view, reachable from the sidebar with a count, lists problems in
configuration that is in use. It does not block anything. Each item says what is wrong, where it
is, how serious it is (critical or warning) and links to the fix. Items clear by themselves when
the problem is fixed. Bad configuration is still blocked at save or publish time, as today (002
FR-014).

**Why this priority**: Most broken calls trace back to something that was fine when published and
broke later. Operators need one place to find these before callers do.

**Independent Test**: Delete a tool used by a published version, let a document fail and leave a
number pointing at an unpublished agent. Confirm all three appear within 15 minutes, each with a
working link. Fix one and confirm it clears within 15 minutes.

**Acceptance Scenarios**:

1. **Given** a number whose agent has no published version or is paused, **When** the checks
   run, **Then** a critical item names the number and the agent.
2. **Given** a published version that refers to a knowledge base whose documents have all failed,
   or that was deleted, **When** the checks run, **Then** a critical item names the agent and the
   knowledge base.
3. **Given** an HTTP tool that failed on more than 20% of at least 10 calls in the last 24 hours,
   **When** the checks run, **Then** a warning shows its failure rate and most common error.
4. **Given** a tool marked "Effect not reviewed" (016), a connection whose credentials expire
   within 7 days (022), an agent with no release tests, or a failed latest release run, **When**
   the checks run, **Then** each appears as a warning.
5. **Given** an item has been fixed, **When** the next check runs, **Then** it disappears, and
   the view records when it was resolved.
6. **Given** the agents list, **When** the "attention" tab is opened, **Then** it includes agents
   with Needs attention items as well as drafts with publish blockers.

---

### User Story 6 - Cap daily spending (Priority: P3)

The workspace owner sets a **daily spend cap** in US dollars and a **warning level** (default 80%
of the cap). At the warning level the owner sees a banner and gets an email. At the cap, new calls,
simulations and test runs are refused until the next day, and calls in progress finish. The owner
can raise the cap for the rest of the day.

**Why this priority**: The prepaid balance already stops spending at zero. A daily cap limits the
damage from a loop or a traffic spike before the balance is gone.

**Independent Test**: Set a cap of $5 with the warning at 80%. Run test calls until $4 is spent and
confirm the banner and email. Continue to $5 and confirm the next call is refused with "daily
spend cap reached" while a call already in progress finishes.

**Acceptance Scenarios**:

1. **Given** a $50 cap with warning at 80%, **When** the day's charges reach $40, **Then** a banner
   shows on every page and the owner is emailed once that day.
2. **Given** the day's charges reach $50, **When** a new call, simulation or test run is
   requested, **Then** it is refused with "daily spend cap reached", and the refusal names the
   time the cap resets.
3. **Given** a call in progress when the cap is reached, **When** it continues, **Then** it is not
   cut, and its charges count toward the day.
4. **Given** the cap is reached, **When** the owner raises it for today, **Then** new calls are
   accepted at once, and the change is in the audit history.
5. **Given** no cap is set, **When** charges accrue, **Then** only the balance limits spending, as
   today.

### Edge Cases

- A version is published while its release run is still running: the run's result applies only to
  that version. A second Publish click joins the same run instead of starting another.
- The release run cannot start because the daily cap is reached or the balance is too low:
  publishing is blocked with that reason, and the owner override still works.
- A test case is edited during a release run: the run uses the case as it was when the run started
  (008).
- Rollback when no earlier version was ever published: the action is unavailable, and pausing is
  offered instead.
- Rollback to a version whose components are no longer offered: refused with the components to
  replace (002), and pausing is offered.
- A number pinned to a version that later can no longer run (retired voice): calls to it are
  refused, and a critical Needs attention item is raised before that date when it is known.
- Pausing an agent that a WhatsApp number or a routing rule (010) sends calls to: those new calls
  are refused as for any paused agent.
- The cap resets at midnight in the time zone chosen with the cap. A call running across midnight is
  charged to the day it started.
- Two charges cross the cap at the same moment: both calls already admitted continue. No call is
  admitted after the cap is seen.
- The fallback number for a paused agent or disabled number is the same number: refused at save.
- An agent's gate is switched off and on again: earlier passing runs remain valid for their
  versions.

## Requirements *(mandatory)*

### Functional Requirements

**Publish gate**

- **FR-001**: Each agent MUST have a release test set: its test cases (008) marked "release",
  defaulting to all cases.
- **FR-002**: Each agent MUST have gate settings: gate on or off (default on), runs per case k
  (default 3, range 1 to 10), required pass rate (default 100% of cases) and whether flaky cases
  block (default yes).
- **FR-003**: With the gate on, publishing a version MUST require a release run against that exact
  version that meets the gate settings. A passing run MUST stay valid for that version for 7 days.
- **FR-004**: Publish MUST offer "Run tests and publish if they pass", showing case count, runs and
  estimated cost. On a pass the version MUST be published automatically. On a failure it MUST NOT
  be published, and the failing and flaky cases MUST be shown.
- **FR-005**: The workspace owner MUST be able to publish a version that has not passed by giving
  a reason (at least 10 characters). The override MUST record who, when, the version, the run and
  its failing cases, and the reason. It MUST be shown on the version and in the audit history.
- **FR-006**: Versions published with the gate off, without release tests, or by override MUST be
  labelled as such in version history.
- **FR-007**: Release runs MUST be billed as test-run feature charges (008).

**Repeat runs**

- **FR-008**: Test runs MUST support running each case k times. A case MUST be "passed" when all k
  runs pass, "failed" when none pass, and "flaky" otherwise, with the pass count shown.
- **FR-009**: Each test case MUST keep its outcome history across runs, including how often it
  was flaky.
- **FR-010**: A manual verdict override (008) MUST apply to the run it was made on, and the case
  outcome MUST be recomputed.

**Rollback and emergency stop**

- **FR-011**: Operators MUST be able to roll back an agent to its previously published version in
  one action with a confirmation, from the agent header and from version history. The release run
  is not required. The rollback MUST be recorded.
- **FR-012**: After a publish or rollback, every new call that starts 60 seconds or more after the
  action MUST use the new published version. Calls in progress MUST keep their version.
- **FR-013**: Operators MUST be able to pause and resume an agent. A paused agent MUST accept no
  new calls of any kind (inbound, outbound, callbacks, browser test calls from the published
  version) within 60 seconds of the pause, and calls in progress MUST continue.
- **FR-014**: Each agent MAY have a fallback number (E.164). While the agent is paused, inbound
  phone calls MUST be transferred to it. Without one, the caller MUST hear the paused message and
  the call MUST end. Either way, the call MUST be recorded as refused with reason "agent paused".
- **FR-015**: Pausing MUST keep the published version, so resuming restores service without
  publishing. Unpublishing (002) stays available as a separate action.

**Phone number version pin and switch**

- **FR-016**: Each phone number's inbound agent MUST have a version mode: latest published (the
  default, and what existing numbers get) or pinned to one version that was published at least
  once.
- **FR-017**: A pinned number MUST use its pinned version regardless of later publishes and
  rollbacks. It MUST show the pinned version and the agent's latest published version.
- **FR-018**: Each number MUST have an enabled switch (default on) and an optional fallback
  number. A disabled number MUST refuse new inbound calls, or transfer them to its fallback, and
  MUST refuse outbound calls and callbacks from it with reason "number disabled". Calls in
  progress MUST continue.
- **FR-019**: Pause (FR-013) MUST take precedence over a number's pin.

**Needs attention**

- **FR-020**: The platform MUST check configuration in use when it changes and at least every
  15 minutes. It MUST list each problem with severity, the affected agent, number, tool, knowledge
  base or connection, a plain explanation and a link to fix it.
- **FR-021**: Checks MUST include at least: a number with no agent, or an agent that is
  unpublished or paused (critical); a published or pinned version that refers to a deleted tool or
  knowledge base, or to a knowledge base with no ready document (critical); a pinned version that
  can no longer run (critical); an HTTP tool failing on more than 20% of at least 10 calls in
  24 hours (warning); a tool with effect not reviewed (016, warning); connection credentials
  failing or expiring within 7 days (022, warning); an agent without release tests, or with a
  failed latest release run (warning); spend at or above the warning level (warning).
- **FR-022**: Items MUST clear automatically when the next check finds the problem fixed, and the
  time they were resolved MUST be kept for 30 days.
- **FR-023**: The sidebar MUST show the count of open critical items. The agents list's
  "attention" status MUST include agents with open items.
- **FR-024**: Needs attention MUST NOT block calls, saves or publishes. Blocking remains with
  save errors and publish blockers (002 FR-014).

**Daily spend cap**

- **FR-025**: The workspace owner MUST be able to set a daily spend cap in USD (off by default) and
  a warning level as a percentage of the cap (default 80%). The day is the calendar day in the
  time zone the owner picks with the cap (default UTC).
- **FR-026**: When the day's charges reach the warning level, the platform MUST show a banner and
  email the owner once that day.
- **FR-027**: When the day's charges reach the cap, the platform MUST refuse new calls,
  simulations and test runs with reason "daily spend cap reached" and the reset time. Calls in
  progress MUST continue.
- **FR-028**: The owner MUST be able to raise the cap for the current day only, or change it from
  the next day. Every change MUST be recorded in the audit history.
- **FR-029**: The cap MUST be checked at the same point as the balance check (001, 003), and use
  the same charges.

**Audit**

- **FR-030**: Publish, override, rollback, pause, resume, pin, number enable or disable, gate
  setting and cap changes MUST be recorded with who, when and what changed, and shown in an audit
  history for each agent and each workspace.

### Key Entities

- **Release test set**: an agent's test cases marked for release.
- **Gate settings**: for each agent, the on/off switch, k, required pass rate and whether flaky
  cases block.
- **Release run**: a test run of the release test set against one version, with k runs per case,
  case outcomes (passed, failed, flaky) and a pass or fail result.
- **Publish override**: the owner's decision to publish a version that has not passed, with its
  reason.
- **Agent pause state**: paused or active, with who and when, and the fallback number.
- **Number routing**: for each phone number, the version mode (latest or pinned version), the
  enabled switch and the fallback number.
- **Attention item**: a detected problem with severity, subject, explanation, fix link, first seen
  and resolved times.
- **Spend cap**: the daily cap, warning level, the current day's total and any raise for today.
- **Audit entry**: one recorded release or safety action.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a fixture set of 20 versions with known failing release cases, 100% are blocked
  from publishing without an override, and 100% of overrides appear in audit history.
- **SC-002**: In 20 rollback trials, every call started 60 seconds or more after the click runs the
  rolled-back version.
- **SC-003**: In 20 pause trials with calls in progress, zero calls in progress are cut, and zero
  new calls are answered by the agent 60 seconds or more after the pause.
- **SC-004**: With a case seeded to pass about half the time, a k = 3 run flags it as flaky in at
  least 70% of runs. A stable case is never flagged.
- **SC-005**: A pinned number serves 100% of its calls on the pinned version across 10 publishes
  and rollbacks.
- **SC-006**: Each seeded configuration fault appears in Needs attention within 15 minutes and
  clears within 15 minutes of the fix.
- **SC-007**: After the day's charges reach the cap, no new call is admitted. The warning email
  arrives within 5 minutes of crossing the warning level.
- **SC-008**: An operator can roll back a bad version in under 30 seconds from the agent page.

## Assumptions

- One user owns each workspace in v1 (001), so "owner" means that user. Team roles and two-person
  approval are later work.
- The release test set uses single-turn test cases (008), whose categories already cover
  out-of-scope, bad behaviour, identity, prompt injection and guardrail tests. Multi-turn persona
  simulations in the gate are later work.
- The gate is on by default for new agents and for existing agents that have test cases. Existing
  agents without test cases publish with a warning rather than being blocked.
- Publishing already reaches new calls within seconds today. The 60-second target is a guaranteed
  upper bound, not a new delay.
- The paused message is fixed platform text in v1, spoken in the agent's language with its voice.
- Daily charges are the same feature and call charges recorded in the transaction history (001).
  Usage reports (001) are unchanged.
- Builds on 001 (balance, charges, audit), 002 (versions, publish blockers), 003 (admission), 005
  (tools, knowledge), 008 (test cases and runs), 010 (phone numbers), 011 (callbacks), 016 (tool
  effects) and 022 (connections).

## Out of scope

- Gradual rollouts (a percentage of calls on a new version) and A/B splits between versions.
- Persona or replay simulations as part of the gate.
- Pinning versions for WhatsApp numbers and outbound agents. Numbers pin the inbound agent only in
  v1.
- Monthly caps, per-agent caps and caps on individual vendors.
- Alerts outside the app and email (Slack, paging), which belong to the operations alerting
  feature (014).
