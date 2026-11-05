# Feature Specification: Outcome analytics (021)

**Feature Branch**: `021-outcome-analytics`
**Created**: 2026-11-05
**Status**: Draft
**Input**: Report business outcomes, not only activity: give every call exactly one handling path
(ai_only, ai_assist, partial, takeover, transfer) and derive containment, zero-touch, transfer
rate and hours saved against a baseline handle time; set KPI targets with red, amber and green
status, favourable or unfavourable deltas, a weekly anomaly callout and drill-in by agent; report
offered, accepted and refused calls with the reason; export a per-call audit record; send daily or
weekly digests and regression or new-issue alerts by email, Slack or webhook; slice by caller
traits, starting with language.

## Why

The dashboard (006) answers "what happened": calls, talk time, cost, cost per call, duration,
turn latency, why calls ended, sentiment, channels, top agents, evaluator pass rates with a change
against the previous period, and agent health. It does not answer the questions a contact-centre
lead is judged on: how many calls did the AI finish on its own, how much human time did it save,
are we meeting our targets, and what changed this week.

Other gaps, from the current product:

- No targets: deltas are shown, but nothing says whether a figure is good or bad.
- Refusals are half visible. Calls refused for the concurrency limit or insufficient credit are
  kept as failed calls with that disconnect reason; an inbound call to a number with no agent or
  an inactive number is dropped with no record at all.
- The call list exports up to 10,000 rows of visible columns as CSV (006 FR-035), but there is no
  per-call record of who and what handled the call for an auditor.
- Outgoing webhooks carry only call events (`call_started`, `call_ended`, `call_analyzed`); there
  is no email or Slack delivery and no digest, so teams learn about regressions and new issues
  only by opening the app.
- Each call records the language it used (012), but no report splits results by it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See how many calls the AI handled on its own (Priority: P1)

Every ended call gets exactly one handling path: ai_only (no person involved), ai_assist (a person
steered or approved but never spoke to the caller), partial (a person took over and handed back,
and the agent finished the call), takeover (the call ended under a person's control) or transfer
(the call left to another number or team). The dashboard shows containment, zero-touch rate,
transfer rate and hours saved against a baseline handle time the workspace sets.

**Why this priority**: Containment and hours saved are the numbers that justify a voice agent;
every other outcome view builds on the handling path.

**Independent Test**: Seed 10 calls: 5 with no intervention, 2 with an approval, 1 takeover with
hand back, 1 takeover to the end and 1 transfer; set the baseline to 6 minutes and confirm
containment 80%, zero-touch 50%, transfer 10% and the hours saved.

**Acceptance Scenarios**:

1. **Given** a call with a whisper and an approved action and no takeover or transfer, **When**
   it ends, **Then** its path is ai_assist.
2. **Given** a call that was taken over, handed back and later transferred, **When** it ends,
   **Then** its path is transfer (transfer takes precedence).
3. **Given** a baseline handle time of 6 minutes and 8 contained calls, one of them partial with a
   2-minute takeover, **When** the dashboard loads, **Then** hours saved is 7 × 6 + 4 = 46
   minutes, shown as 0.8 hours.
4. **Given** an agent with its own baseline of 9 minutes, **When** hours saved is computed,
   **Then** that agent's calls use 9 minutes and the others the workspace baseline.
5. **Given** a workspace without live supervision in use, **When** the dashboard loads, **Then**
   every call that was not transferred counts as ai_only and the tiles still render.
6. **Given** calls that never connected (no answer, busy, refused), **When** rates are computed,
   **Then** they are excluded from containment and appear in the call acceptance report instead.

---

### User Story 2 - Set targets and see which are met (Priority: P1)

An operator sets targets for key figures for the workspace and, optionally, per agent: for
example containment at least 70%, transfer rate at most 15%, median turn latency at most 1.2 s.
Each figure shows green (met), amber (missed by no more than its tolerance) or red, and the
dashboard says "N of M meeting target". Changes against the previous period are coloured by
whether they are good news for that figure. A weekly callout names the largest unusual change, and
every figure drills into a per-agent table.

**Why this priority**: Targets turn the dashboard from a report into a status check; drill-in
shows which agent to fix.

**Independent Test**: Set containment ≥ 70% with 5-point tolerance and cost per call ≤ 0.40; seed
data giving 67% and 0.45; confirm amber and red, "0 of 2 meeting target", a falling cost shown as
favourable, and the per-agent table.

**Acceptance Scenarios**:

1. **Given** a containment target of 70% with 5 points of tolerance, **When** containment is 67%,
   **Then** it shows amber "3 pp below target".
2. **Given** a cost per call target of at most 0.40, **When** cost falls from 0.48 to 0.45,
   **Then** the delta shows as favourable and the status as red.
3. **Given** fewer than 20 counted calls in the period for a figure, **When** it renders,
   **Then** it shows grey "Not enough calls" instead of a status.
4. **Given** the last complete week, **When** the dashboard loads, **Then** a callout names the
   figure and agent with the largest unfavourable change against the previous 8 weeks, for
   example "Transfer rate for Billing rose from 12% to 21%", or "No unusual changes this week".
5. **Given** a figure, **When** the operator opens it, **Then** a table lists each agent's value,
   target, status, delta and call count, and an agent row opens its calls in Call History with
   the period and agent filters applied.

---

### User Story 3 - Know which calls were refused and why (Priority: P2)

A Call acceptance report shows, for a period, calls offered (every attempt that reached
Callwright), accepted (connected to an agent) and refused, with the reason: number not linked to
an agent, number inactive, agent not published, concurrency limit, insufficient credit, outside
calling hours, do-not-call. Outbound attempts that rang but were not answered are shown
separately as not connected.

**Why this priority**: A refused call is a lost customer that today leaves no trace; the report
shows capacity and configuration problems directly.

**Independent Test**: Place one inbound call to an unlinked number, one while at the concurrency
limit and one accepted call, and confirm 3 offered, 1 accepted and 2 refused with reasons.

**Acceptance Scenarios**:

1. **Given** an inbound call to a number with no agent, **When** it is refused, **Then** a refused
   attempt is recorded with the number, time, masked caller number and "Number not linked to an
   agent".
2. **Given** the period's report, **When** it loads, **Then** it shows daily offered, accepted and
   refused counts, a breakdown by reason, and a list of refused attempts filterable by reason,
   number and agent.
3. **Given** refused attempts above 5% of offered calls in a day, **When** the report loads,
   **Then** that day is highlighted.

---

### User Story 4 - Export a per-call audit record (Priority: P2)

From a call, or for a period, an operator exports the audit record: who and what handled each call
(agent, version, handling path, supervisors), every intervention and approval with its outcome and
time, quality results and human reviews, how the call ended and what it cost. Formats are CSV and
JSON.

**Why this priority**: Regulated teams must show who did what on a call; it is the record an
auditor asks for.

**Independent Test**: Export one call with a whisper and an approval as JSON and a week of calls
as CSV, and confirm every field is present and matches the call view.

**Acceptance Scenarios**:

1. **Given** a call view, **When** the operator chooses "Export audit record" as JSON, **Then** a
   file downloads with the call, its path and every intervention in time order.
2. **Given** a period of 30,000 calls, **When** the operator exports CSV, **Then** the export runs
   in the background, the operator is told when it is ready, and the download link works for 7
   days.
3. **Given** the default settings, **When** an export is made, **Then** phone numbers are masked
   to the last 4 digits; full numbers require choosing "Include full numbers".
4. **Given** any export, **When** it is created, **Then** the export itself is recorded with who,
   when, scope and format.

---

### User Story 5 - Get digests and alerts where the team works (Priority: P2)

An operator sets up a daily or weekly digest and alerts, and chooses where they go: email
addresses, a Slack channel, or a webhook. The digest summarises calls, containment, targets met,
the week's callout, new and regressed issues, refused calls and spend. Alerts fire when an issue
regresses (019), detection finds a new issue, a target turns red, or a supervision alert turns
critical (020).

**Why this priority**: Most problems are found late because nobody opened the dashboard; a short
message at the right time fixes that.

**Independent Test**: Add an email and a Slack destination, send a test, trigger a regression on a
test agent, and confirm one alert per destination within 5 minutes and no repeat within the hour.

**Acceptance Scenarios**:

1. **Given** a weekly digest for Monday 08:00 in Europe/London, **When** Monday 08:00 arrives,
   **Then** each destination receives the digest for the previous Monday to Sunday.
2. **Given** a reopened issue (019), **When** it reopens, **Then** an alert with the agent, issue,
   version and a link is sent to every destination subscribed to regression alerts.
3. **Given** the same alert fired twice within an hour, **When** the second fires, **Then** it is
   not sent again and the first message's count is noted in the next digest.
4. **Given** a Slack destination whose address stops working, **When** delivery fails, **Then** it
   is retried, then marked failing in settings with the last error, and the other destinations
   still receive the alert.
5. **Given** a webhook destination, **When** an alert is sent, **Then** it is signed the same way as
   the existing call webhooks.

---

### User Story 6 - Slice results by caller language (Priority: P2)

Every outcome figure can be filtered and broken down by the caller's language, so a team can see
whether, for example, Hindi callers are transferred more often than English callers.

**Why this priority**: Language is recorded on every call already; it is the first trait that
shows whether an agent serves all callers equally.

**Independent Test**: Seed calls in English and Hindi with different transfer rates and confirm the
breakdown and the filter.

**Acceptance Scenarios**:

1. **Given** calls in two languages, **When** the operator picks "Break down by caller language",
   **Then** each figure shows a row per language with its value, status and call count.
2. **Given** a call that switched from English to Hindi, **When** it is counted, **Then** it
   counts under Hindi, the language most of the caller's turns were in.

---

### User Story 7 - Slice by automatic caller tags (Priority: P3)

After each call, the system tags it from a workspace tag list (for example "billing question",
"repeat caller", "noisy line") with a confidence for each tag. Tags with confidence of at least
0.7 can be used to filter and break down every outcome figure. A person can correct a tag.

**Why this priority**: Tags reveal which kinds of calls fail; they depend on the language slicing
and the post-call pipeline being in place.

**Independent Test**: Define three tags, run tagging on 20 seeded calls, correct one tag, and
confirm the breakdown counts only tags at or above 0.7 plus the corrected one.

**Acceptance Scenarios**:

1. **Given** a tag at confidence 0.62, **When** figures are broken down by tag, **Then** that
   call does not count under the tag, and the call view shows it as "low confidence".
2. **Given** a person removes a tag, **When** figures are recomputed, **Then** the call no longer
   counts under it and the correction is kept.
3. **Given** an operator adds a tag named after a protected trait (for example religion or
   health), **When** they save it, **Then** it is refused.

---

### Edge Cases

- A call is still in post-call processing: its path is set when processing ends; figures count it
  from then.
- Late supervision events after the call ends (an approval recorded after hang-up): the path is
  recomputed once processing ends and never after.
- A target set mid-period: status uses the target in force at the end of the period.
- Lower-is-better figures (transfer rate, cost per call, latency) and higher-is-better figures
  (containment, pass rate) colour deltas oppositely.
- A week with fewer than 30 counted calls for an agent: that agent is left out of the anomaly
  callout.
- Fewer than 4 previous weeks of history: the callout says "Not enough history yet".
- An export of a period with no calls: an empty file with headers is produced, not an error.
- An export includes calls whose transcripts were purged: the record keeps every field except
  transcript-derived text and says so.
- Digest timezone changes (daylight saving): sent at the local time chosen, not a fixed UTC time.
- All destinations fail: the alert is kept in the app's alert list and shown in the next digest.
- Simulated and test calls: never counted in outcomes, acceptance, digests or exports of live
  calls.

## Requirements *(mandatory)*

### Functional Requirements

**Handling path and outcome figures (Story 1)**

- **FR-001**: System MUST set exactly one handling path on every ended live call that connected,
  by precedence: transfer (the call ended by transfer), takeover (a person was in control when the
  call ended), partial (a person took over and handed back), ai_assist (a whisper, an answered
  approval, a handled action or a sent assist card, 020), otherwise ai_only.
- **FR-002**: System MUST show for the selected period and agents: containment (ai_only,
  ai_assist and partial over counted calls), zero-touch rate (ai_only over counted calls),
  transfer rate, takeover rate and the count per path.
- **FR-003**: Workspaces MUST have a baseline handle time (default 6 minutes, 1 to 60) with an
  optional override per agent.
- **FR-004**: Hours saved MUST be the sum over counted calls of: the baseline for ai_only and
  ai_assist calls; the baseline minus the takeover time, not below zero, for partial calls; zero
  for takeover and transfer calls; shown in hours with one decimal.
- **FR-005**: Counted calls MUST be ended live calls that connected; test and simulated calls and
  calls that never connected are excluded.

**Targets, deltas and anomalies (Story 2)**

- **FR-006**: Users MUST be able to set targets for the workspace and per agent on: containment,
  zero-touch rate, transfer rate, hours saved per week, average handle time, median and 95th
  percentile turn latency, cost per call, headline evaluator pass rate, share of positive
  sentiment and share of reviews rated acceptable (019). Each has a fixed direction (higher or
  lower is better), a target value and a tolerance (default 5% of the target for currency and
  time figures, 5 points for rates).
- **FR-007**: Status MUST be green when the target is met, amber when missed by no more than the
  tolerance, red otherwise, and grey "Not enough calls" with fewer than 20 counted calls. An agent
  target overrides the workspace target for that agent.
- **FR-008**: The dashboard MUST show "N of M meeting target" over figures with a target.
- **FR-009**: Every change against the previous period MUST be labelled favourable or unfavourable
  by the figure's direction, and unchanged within 0.5 points or 0.5%.
- **FR-010**: Each week (Monday to Sunday in the workspace's report timezone) System MUST find,
  across figures and agents with at least 30 counted calls in the week, the largest unfavourable
  change measured against the mean and spread of the previous 8 weeks, and show it when it is at
  least 2 standard deviations away; otherwise "No unusual changes this week". At least 4 previous
  weeks are required.
- **FR-011**: Every figure MUST open a per-agent table (value, target, status, delta, calls),
  sortable by each column, and each row MUST link to Call History filtered by that agent, period
  and, where it applies, handling path.

**Call acceptance (Story 3)**

- **FR-012**: System MUST record every call attempt that reaches Callwright, including inbound
  calls to numbers with no agent or an inactive number, with the time, number, agent (if any),
  direction, masked caller number and outcome: accepted, refused (with reason) or not connected.
- **FR-013**: Refusal reasons MUST be: number not linked to an agent, number inactive, agent not
  published, concurrency limit, insufficient credit, outside calling hours, do-not-call, other
  (with detail).
- **FR-014**: The report MUST show daily offered, accepted, refused and not-connected counts,
  refusals by reason, number and agent, a list of refused attempts, and highlight days where
  refusals exceed 5% of offered.
- **FR-015**: Refused attempts MUST be kept for 90 days.

**Audit record export (Story 4)**

- **FR-016**: The audit record of a call MUST contain: call id, start and end times, channel,
  direction, numbers, agent, agent version, caller language, handling path, supervisors involved,
  every intervention and approval with outcome and times (020), evaluator results with any
  overrides and the final human review (019), disconnect reason and total cost.
- **FR-017**: Users MUST be able to export one call or a period (filtered by agent, path,
  channel and language, at most 100,000 calls) as CSV (one row per call, plus a second file with
  one row per intervention) or JSON (one nested object per call).
- **FR-018**: Period exports over 1,000 calls MUST run in the background, notify the user when
  ready, and keep the file for 7 days.
- **FR-019**: Phone numbers MUST be masked to the last 4 digits unless the user chooses to include
  full numbers; every export MUST be recorded with who, when, scope, format and masking.

**Digests and alerts (Story 5)**

- **FR-020**: Users MUST be able to add destinations of three kinds: email (up to 20 addresses),
  Slack (an incoming webhook address) and webhook (signed like call webhooks), send a test, and
  see each destination's last delivery and error.
- **FR-021**: Users MUST be able to schedule a digest daily or weekly (day and hour, in a chosen
  timezone) per destination, containing: counted calls, containment, hours saved, "N of M meeting
  target" with the red figures, the weekly callout, new and regressed issues, refused attempts,
  spend, and links into the app.
- **FR-022**: System MUST send alerts, each type switchable per destination, for: an issue
  regressed (019), a new issue from detection (009), a target turned red, and a critical
  supervision alert (020).
- **FR-023**: Alerts MUST be sent within 5 minutes of the event, retried on failure as call
  webhooks are, and not repeated for the same agent and type within 1 hour; suppressed repeats
  MUST be counted in the next digest.
- **FR-024**: Every alert MUST also appear in an in-app alert list kept for 90 days.

**Caller-trait slicing (Stories 6 and 7)**

- **FR-025**: Every outcome figure, the acceptance report and exports MUST filter and break down
  by caller language; a call counts under the language of most of its caller turns.
- **FR-026**: Outcome figures MUST also break down by caller line noise (quiet, moderate, noisy)
  when audio checks (019) have measured it.
- **FR-027**: Workspaces MUST be able to define up to 30 call tags with a name and a description;
  names that describe protected traits (age, ethnicity, religion, health, disability, sexual
  orientation, gender identity, and similar) MUST be refused.
- **FR-028**: After each call, System MUST assign tags with a confidence from 0 to 1, billed with
  post-call analysis; only tags at or above 0.7, or added by a person, count in breakdowns.
  People MUST be able to add or remove tags, and corrections are kept.

### Key Entities

- **Handling Path**: the single path of one call, with the facts that set it (transfer, takeover
  spans, interventions).
- **Baseline Handle Time**: per workspace, with optional per-agent values.
- **KPI Target**: a figure, scope (workspace or agent), direction, target value, tolerance and
  the time it took effect.
- **Weekly Callout**: the week's largest unusual unfavourable change, its figure, agent and size.
- **Call Attempt**: one offered call with its outcome and refusal reason.
- **Audit Export**: one export job: scope, format, masking, requester, status, file expiry.
- **Destination**: an email list, Slack address or webhook, with its subscriptions and delivery
  health.
- **Digest Schedule**: frequency, day, hour, timezone and destination.
- **Alert**: one event sent to destinations: type, agent, subject, time, deliveries.
- **Call Tag / Tag Assignment**: a workspace tag and its assignment to a call with confidence and
  source (automatic or person).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of counted calls have exactly one handling path, checked nightly.
- **SC-002**: Containment, zero-touch, transfer rate and hours saved match an independent recount
  of seeded calls in 100% of tests, including precedence cases.
- **SC-003**: The dashboard with targets for "last 30 days" and 100,000 calls renders in under 2
  seconds at the 95th percentile, as 006 requires today.
- **SC-004**: An operator can go from a red figure to the calls of the agent behind it in under
  30 seconds.
- **SC-005**: 100% of call attempts reaching Callwright, including those to unlinked or inactive
  numbers, appear in the acceptance report.
- **SC-006**: A period export of 10,000 calls is ready within 2 minutes in 95% of cases, and every
  exported field matches the call view in tests.
- **SC-007**: 99% of digests arrive within 15 minutes of their scheduled time, and 95% of alerts
  within 5 minutes of the event.
- **SC-008**: Within a month of launch, at least half of active workspaces have at least one
  target set (product metric).

## Assumptions

- Interventions (whisper, approval, takeover, hand back, assist card) come from live supervision
  (020). Until 020 ships, every call that is not a transfer is ai_only.
- Transfers are calls that ended by the transfer call control (003, 005).
- A baseline handle time of 6 minutes is Callwright's default for a human-handled call; teams are
  expected to set their own.
- Workspaces gain a report timezone (default: the timezone of the user who sets the first digest)
  for weekly callouts and digests; dashboards still use the viewer's timezone (006).
- Email and Slack sending are new capabilities; webhook delivery and signing reuse the existing
  call webhooks.
- Operations alerts about the platform itself (health, outages, provider errors) belong to
  reliable operations (014), not here.
- Issue regressions and audio measures come from 019; new issues from 009.
- Default thresholds (20 calls, 30 calls per week, 2 standard deviations, 8 weeks, 0.7 confidence,
  5% refused, 1-hour repeat window, 7-day file life, 90-day retention) are Callwright's starting
  targets.

## Out of Scope

- Revenue or cost-avoidance figures beyond hours saved.
- Custom formulas for figures; scheduled exports to storage buckets.
- Alerts by SMS or phone, paging and on-call rotation.
- Slicing by traits inferred from the voice (age, gender, accent).
- Benchmarks across workspaces.
