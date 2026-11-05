# Feature specification: reliable operations (014)

Created: 2026-11-05. Status: Draft.

## Why
Callwright can cut live calls and fail without anyone noticing.

- **Deploys cut calls.** A voice worker gets 30 seconds to stop. Every call still running 30
  seconds after a deploy starts is dropped, although an agent allows calls of up to 10 minutes
  by default and 60 minutes at most.
- **Health says "ok" no matter what.** The API's health check returns a fixed "ok" without
  looking at the database, the cache, the media server or the voice workers. Nothing outside the
  hosting provider checks it.
- **There are no alerts.** A call that never gets an agent, a worker that dies mid-call, a vendor
  key that stops working or a stuck job queue shows up only when someone opens the dashboard or a
  customer complains. The reaper closes a call whose worker went quiet after 60 seconds, but it
  tells nobody.
- **Tracing is off in the hosted setup.** Tracing is built into the API and the voice worker, but
  the realtime host exports nothing, so a slow or failed call can only be studied from its stored
  events.
- **Nobody knows what happens when a part dies.** The realtime host runs the media server, the
  cache, the jobs worker, the voice worker and the phone gateway on one machine, and the effect
  of losing each one has never been measured.

This feature makes deploys safe for calls, gives a real readiness signal that is checked from
outside, sends alerts to Slack, email or a webhook (silent failures first), turns tracing on with
sampling that keeps the interesting calls, and adds a repeatable crash drill.

## User scenarios and testing

### User story 1: deploys never cut a call (P1)
An operator deploys a new voice worker while calls are in progress. The old worker stops taking
new calls at once and keeps every call it holds running until the call ends. The new worker takes
every new call from the moment it is ready. The operator can see how many calls are still
draining and how old the oldest one is.

**Why this priority**: today every deploy can cut every live call. That is the most direct
caller harm in this feature and the cheapest to fix.

**Independent test**: start 5 test calls of 3 to 8 minutes, deploy, and start 5 more calls
during the deploy. All 10 calls end normally, none with a shutdown reason.

**Acceptance scenarios**:
1. **Given** a call that has run for 2 minutes, **When** a deploy starts, **Then** the call
   continues on the old worker until the caller or the agent ends it, and its disconnect reason
   is the normal one.
2. **Given** a deploy in progress with the old worker draining, **When** a new call is admitted,
   **Then** the new worker answers it, and the caller waits no longer than on any other call.
3. **Given** a draining worker whose last call ends, **When** no call is left, **Then** the worker
   stops within 10 seconds and the deploy is reported done.
4. **Given** a call still running when the drain window closes, **When** the worker must stop,
   **Then** the agent says a short apology, the call ends with reason `worker_shutdown`, and the
   deploy record counts it as a cut call.
5. **Given** a draining worker, **When** the idle shutdown checks the host, **Then** the host
   counts as busy and stays on.

---

### User story 2: an honest readiness signal, checked from outside (P1)
An operator, or an uptime service outside the hosting provider, asks Callwright whether it can
take calls. The answer names each part that matters (database, cache and queue store, media
server, voice workers, jobs worker) and whether it is up. A deeper check, at most every 5 minutes,
confirms that each configured speech, language and voice vendor answers a real request. The
outside service checks every 60 seconds and treats 3 failures in a row as down.

**Why this priority**: alerts (story 3) need a true signal to work from, and a fixed "ok" hides
every outage.

**Independent test**: stop the cache on a staging host; within 1 minute readiness reports the
cache as down and the overall status as not ready; within 4 minutes the outside check has
recorded the outage.

**Acceptance scenarios**:
1. **Given** every part is up, **When** readiness is asked, **Then** it answers "ready" within 3
   seconds and lists each part with its status and response time.
2. **Given** the media server does not answer within 1 second, **When** readiness is asked,
   **Then** the media server is "down", the overall status is "not ready", and the other parts are
   still reported.
3. **Given** the realtime host is powered off because it was idle, **When** readiness is asked,
   **Then** the overall status is "asleep", the check does not wake the host, and it does not
   count as activity for the idle timer.
4. **Given** a deep check ran 2 minutes ago, **When** another deep check is asked for, **Then**
   the cached result is returned with its age and no vendor is called.
5. **Given** 3 outside checks in a row fail, **When** the third fails, **Then** a P1 "Callwright
   is down" alert is sent (story 3); the first success afterwards sends its resolved line.

---

### User story 3: silent failures reach the team in Slack, email or a webhook (P1)
The team chooses where alerts go: a Slack channel, email addresses or a webhook. Callwright
checks a set of alert rules all the time. When a rule fires, the team gets one message that says
what broke, how badly, since when and where to look. P1 alerts repeat every hour and P2 alerts
every 4 hours until the condition clears, and then a single RESOLVED message follows. The first
rules cover failures that are otherwise silent.

**Why this priority**: there is no alerting at all today. A broken vendor key or a dead worker
can fail every call for hours.

**Independent test**: with a Slack destination set, revoke a vendor key on staging and place a
call; a P1 alert naming the vendor and the error class arrives within 2 minutes, and restoring
the key leads to a RESOLVED message.

**Acceptance scenarios**:
1. **Given** a call admitted 60 seconds ago that no voice worker has picked up, **When** the
   rules run, **Then** a P1 "call never got an agent" alert is sent with the call's link.
2. **Given** a P1 alert that keeps firing, **When** an hour passes, **Then** it is sent again,
   marked as a repeat with how long it has been open; it is not sent more often than that.
3. **Given** an open P2 alert, **When** the condition has been clear for one evaluation window,
   **Then** one RESOLVED message is sent that refers to the original alert, and no more repeats.
4. **Given** a Slack destination that fails, **When** delivery has failed 3 times in 5 minutes,
   **Then** the alert goes to the other destinations for its severity and the failure is
   recorded.
5. **Given** an operator who mutes a rule for 2 hours with a reason, **When** it fires in that
   time, **Then** no message is sent, the firing is still recorded, and the mute ends on time.
6. **Given** a new destination, **When** the operator sends a test alert, **Then** it arrives
   marked as a test.

---

### User story 4: workspace owners hear about their own problems (P2)
A workspace owner adds their own Slack channel, email or webhook for alerts about their
workspace: many of their calls failing, their webhook endpoint failing, credit running low, a
phone number that has stopped receiving calls.

**Why this priority**: customers find out about their own outages first, but the platform-level
alerts in story 3 come first.

**Independent test**: point a workspace's call webhook at an endpoint that returns errors, place
10 calls, and confirm that the workspace's alert destination gets a "webhook deliveries failing"
alert and the platform destination gets nothing about it.

**Acceptance scenarios**:
1. **Given** a workspace with an email destination, **When** more than half of its webhook
   deliveries fail over 30 minutes (at least 10 deliveries), **Then** the workspace gets a P2
   alert naming the endpoint, not the payloads.
2. **Given** two workspaces, **When** one has an alert, **Then** the other never sees it or its
   details.

---

### User story 5: traces for the calls that matter (P2)
An engineer opens a failed or slow call and follows its trace across the API, the jobs worker
and the voice worker. Every call with an error, a failure or a slow turn is kept; about 1 in 10
ordinary calls is kept as well.

**Why this priority**: it shortens the diagnosis of what alerts find. Calls already store their
events, so this adds depth and is not the first signal.

**Independent test**: run 50 test calls on staging with 5 forced vendor errors; all 5 failed
calls and about 5 of the 45 ordinary calls have traces, and each kept trace is complete.

**Acceptance scenarios**:
1. **Given** a call where one turn took 4 seconds, **When** the call ends, **Then** its whole
   trace is kept.
2. **Given** the tracing backend is unreachable, **When** calls run, **Then** they are unaffected
   and the dropped data is counted.
3. **Given** a kept trace, **When** an engineer reads it, **Then** it holds no caller words, agent
   replies or full phone numbers (017).

---

### User story 6: a crash drill for each part (P3)
On a staging copy, with test calls running, the team stops one part at a time (voice worker,
jobs worker, media server, cache, phone gateway, an API instance, the whole realtime host, the
database connection) and records what callers hear, which calls are lost, how they are recorded,
how fast an alert fires and how long recovery takes.

**Why this priority**: it checks stories 1 to 3 against real failures and documents how fragile
the single host is. It needs those stories in place first.

**Independent test**: run the voice-worker drill with 5 calls in progress and confirm that the
recorded results match the expected outcomes or that each gap has a tracked issue.

**Acceptance scenarios**:
1. **Given** 5 calls in progress, **When** the voice worker process is killed, **Then** each
   call is marked ended with a system reason within 90 seconds, an alert fires within 3 minutes,
   and new calls succeed once the worker is back.
2. **Given** a finished drill, **When** the team opens the drill log, **Then** it shows the date,
   the build, the part, each measurement and pass or fail against the expectations.

### Edge cases
- A deploy starts while an earlier deploy is still draining: the oldest worker keeps draining,
  only the newest worker takes new calls, and the window of each draining worker is unchanged.
- A drain window closes while the agent is speaking: the apology waits for the current sentence
  to finish, for no more than 5 seconds.
- The host's idle shutdown and a deploy coincide: a draining worker, or a deploy that has not
  finished, counts as busy.
- Readiness while the host is waking: status "starting" for up to 3 minutes after the wake
  request, then "not ready" if parts are still down.
- The outside check must not keep the host awake: readiness is excluded from the activity marker,
  as health is today.
- A vendor's deep check fails because of an expired key: the deep check reports "auth" for that
  vendor and the billing-or-auth rule fires; it does not count toward "Callwright is down".
- An alert storm (for example, the cache is down and every call fails): rules caused by an open
  "part down" alert are folded into it as "also affected" and do not send their own messages.
- The alerting system dies: the outside service also expects a heartbeat from the alert
  evaluator every 5 minutes and alerts on its own when the heartbeat stops.
- Email destination bounces: after 3 hard bounces the address is disabled and the team is told
  on the remaining destinations.
- Rules that need the realtime host do not run while it is asleep by design.
- A mute set on a P1 rule ends after 24 hours at most.

## Requirements

### Functional requirements

Drain on deploy
- **FR-001**: When asked to stop, a voice worker MUST stop accepting new calls at once and keep
  every call it holds running until the call ends.
- **FR-002**: The drain window MUST be the longest call duration an agent can be set to (3,600
  seconds) plus 5 minutes. A call still running at the end MUST get a short spoken apology and
  end with disconnect reason `worker_shutdown`.
- **FR-003**: A deploy MUST start the new voice worker and confirm it can take calls before the
  old worker starts draining. New calls MUST go only to workers that are not draining.
- **FR-004**: Jobs in progress on a stopping jobs worker or simulation worker MUST finish within
  5 minutes or go back to the queue, and running a job again MUST NOT repeat its effects (a
  callback still dials at most once, 011).
- **FR-005**: The idle shutdown MUST treat a draining worker, or a deploy that has not finished,
  as busy.
- **FR-006**: Operators MUST be able to see, per deploy, the number of calls still draining and
  the age of the oldest, and MUST be able to end a drain early after a confirmation that states
  how many calls will be cut.
- **FR-007**: Each deploy MUST record its start, its end and the number of calls it cut.

Readiness and health
- **FR-008**: The existing health check MUST stay a cheap "process is up" answer with no
  dependency checks.
- **FR-009**: A readiness check MUST report each part (database, cache and queue store, media
  server, at least one voice worker that takes calls, the jobs worker's last heartbeat) with its
  status and response time. Each part check MUST time out after 1 second, and the whole answer
  MUST come within 3 seconds.
- **FR-010**: Readiness MUST give one overall status: `ready`, `degraded` (only parts that do not
  stop calls are down), `not_ready`, `starting` or `asleep` (realtime host powered off by
  design). Asking MUST NOT wake the host or count as activity.
- **FR-011**: A deep check MUST send one small real request to each configured speech
  recognition, language model and voice vendor, and confirm that the phone gateway is
  registered. It MUST run at most once every 5 minutes, MUST return the cached result with its
  age in between, MUST classify each failure (billing, auth, overloaded, transient; 015), and MUST
  be available only to platform operators.
- **FR-012**: An uptime service outside the hosting provider MUST check readiness every 60
  seconds. 3 failures in a row MUST count as down; "asleep" MUST count as up.
- **FR-013**: While the realtime host is awake, a scripted test call MUST run every 60 minutes
  against a platform test agent and check that the agent speaks within 5 seconds. It MUST NOT
  count as activity and MUST NOT be billed to a customer.

Alert rules and delivery
- **FR-014**: Alert rules MUST be defined in one reviewed place, changed through normal review.
  Each rule has an id, a title, a severity (P1 or P2), a condition, an evaluation window, a
  threshold, a minimum sample where it applies, a scope (platform or workspace) and a runbook
  section.
- **FR-015**: The first rules MUST be the silent-failure set:
  - a. Call never got an agent: an admitted call not picked up by a voice worker within 60
    seconds (P1, from the first occurrence).
  - b. Call lost its worker: a call in progress with no worker heartbeat for 60 seconds (P1).
  - c. Call events lost: a worker could not deliver call events or the end-of-call report after
    its retries (P2).
  - d. First billing or auth error from any vendor (P1, from the first occurrence).
  - e. Dead air: more than 5% of calls in the last hour had dead air (an agent turn with no
    audio, or a call ended for silence after the agent failed to answer), with at least 20
    calls (P2).
  - f. Telemetry missing: no call metrics or heartbeats for 10 minutes while calls are in
    progress (P2).
  - g. Queue stuck: the oldest waiting job is older than 15 minutes, or no job finished in 15
    minutes while jobs were waiting (P2).
  - h. Callwright is down: the outside check failed 3 times in a row (P1).
- **FR-016**: The next rules MUST be: system-caused call failures above 10% over 15 minutes with
  at least 10 calls (P1); recordings not settled 30 minutes after their call ended (P2); readiness
  `degraded` for 10 minutes (P2); deep check failing for one vendor twice in a row (P2).
- **FR-017**: A P1 alert MUST repeat every hour and a P2 alert every 4 hours while it fires. When
  the condition has cleared for one evaluation window, one RESOLVED message MUST be sent. Each
  rule and scope MUST have at most one open alert.
- **FR-018**: Each message MUST state the severity, the rule's title, the value that crossed the
  threshold, the start time, the scope (workspace, agent, vendor or part), a link to the runbook
  section and a link to the affected calls. It MUST NOT contain caller words, agent replies or
  full phone numbers.
- **FR-019**: Alert destinations MUST include a Slack channel, email addresses and a webhook.
  Webhook alerts MUST be signed and retried like call webhooks. Each severity routes to one or
  more destinations.
- **FR-020**: Delivery MUST be retried 3 times over 5 minutes. After that the alert MUST go to the
  other destinations for its severity and the failure MUST be recorded. An email address with 3
  hard bounces MUST be disabled and the team told.
- **FR-021**: Operators MUST be able to send a test alert to any destination.
- **FR-022**: Operators MUST be able to mute a rule for a set time with a reason. P1 mutes end
  after 24 hours at most. Firings during a mute MUST be recorded and listed.
- **FR-023**: When a "part down" or "Callwright is down" alert is open, alerts caused by it MUST
  be folded into it as "also affected" and not sent on their own.
- **FR-024**: The alert evaluator MUST send a heartbeat to the outside service every 5 minutes; a
  missing heartbeat MUST raise an alert from that service.
- **FR-025**: Workspace owners and admins MUST be able to add their own destinations for
  workspace rules: system-caused call failures in their workspace, their webhook endpoint
  failing (more than half of at least 10 deliveries over 30 minutes), credit below their set
  level, and a phone number with no inbound call reaching an agent for a set time they choose.
  Workspace alerts and destinations are tenant data under row-level security.
- **FR-026**: Every alert, repeat, resolve, mute and delivery attempt MUST be stored and listed,
  newest first, for 90 days.

Tracing
- **FR-027**: The API, the jobs worker and the voice worker MUST export traces in the hosted
  setup.
- **FR-028**: Sampling MUST be decided per call after the call ends. Every call with an error, a
  failure reason, a provider switch (015) or a turn slower than 3 seconds MUST be kept, plus 10%
  of the rest. A kept call MUST keep all its spans.
- **FR-029**: Frequent signals (audio levels, queue depth, per-second state) MUST be recorded as
  counts and distributions, never as a log line per second per call.
- **FR-030**: Traces and logs MUST follow 017's masking rules.
- **FR-031**: Export MUST use a bounded buffer that drops the oldest data when the backend is slow
  or down, MUST count what it drops, and MUST add less than 5 ms per turn.
- **FR-032**: The call page MUST link to the call's trace when one was kept.

Crash drill
- **FR-033**: A drill plan MUST exist for each part: voice worker, jobs worker, media server,
  cache and queue store, phone gateway, an API instance, the whole realtime host, and loss of the
  database connection. Each plan states how the part is stopped and the expected outcome.
- **FR-034**: Each drill MUST run on a staging copy with at least 5 test calls in progress (at
  least 1 of them a phone call) and MUST record: how long callers heard silence, the calls lost,
  how each lost call was recorded (status and reason), time to the first alert, time to recover,
  and whether new calls work afterwards.
- **FR-035**: Expected outcomes for every drill: an alert within 3 minutes; every affected call
  ended with a system reason within 90 seconds of the failure; no call left "in progress" after
  recovery; new calls work within 5 minutes of the part coming back; no call charged twice.
- **FR-036**: Drill results MUST be stored with the date and build. Each drill MUST run again
  after any change to how the hosts are laid out, and at least once a quarter. Each missed
  expectation MUST become a tracked issue.

### Key entities
- **Readiness report**: overall status, check time, and per part: name, status, response time,
  error class.
- **Deep check result**: per vendor and the phone gateway: status, error class, response time,
  checked at, cost.
- **Alert rule**: id, title, severity, scope, condition, window, threshold, minimum sample,
  runbook section, enabled.
- **Alert**: rule, scope, opened at, last sent at, repeat count, resolved at, folded alerts,
  muted until and why.
- **Alert destination**: kind (Slack, email, webhook), target, severities, owner (platform or
  workspace), status (active, failing, disabled).
- **Delivery attempt**: alert, destination, time, result.
- **Deploy record**: build, started, ended, calls draining over time, calls cut.
- **Drill run**: part, build, date, measurements, expected and actual outcome, linked issues.

## Success criteria

- **SC-001**: Over 10 deploys made while test calls run, no call is cut (today, any call running
  more than 30 seconds into a deploy is dropped).
- **SC-002**: When the API or the realtime host becomes unreachable, the team gets a P1 message
  in Slack within 4 minutes.
- **SC-003**: Every rule in the silent-failure set fires in a staged test of its condition within
  its window plus 2 minutes, and resolves within 5 minutes of the condition clearing.
- **SC-004**: Over 7 days with normal idle sleeps, no "down" alert is caused by the host sleeping
  by design.
- **SC-005**: Readiness answers within 3 seconds for 99% of requests, and the deep check calls
  each vendor no more than 288 times a day.
- **SC-006**: No open alert sends more than one message per hour (P1) or per 4 hours (P2).
- **SC-007**: Every failed call and at least 8% of ordinary calls have a complete trace, and
  tracing adds less than 5 ms to turn latency at the 95th percentile.
- **SC-008**: Every drill in the plan has run at least once, and each one meets the expected
  outcomes or has an open issue for every gap.

## Assumptions
- The single realtime host and its idle shutdown stay as they are; this feature does not add
  hosts.
- The outside check uses an uptime service outside the hosting provider; picking one is a plan
  decision.
- Slack delivery uses a channel's incoming webhook URL; no Slack app is needed.
- Email uses a transactional email service; the sign-in email setup is not reused if its sending
  limits are too low.
- Platform alert destinations and the platform rules are managed by the Callwright team only;
  workspace rules are a small fixed set in this version.
- The staging copy for drills can be the hosted realtime host during a maintenance window when no
  separate staging host exists; drills never run during customer calls.
- Error classes (billing, auth, overloaded, transient) come from 015; masking rules come from 017.
- The scripted test call (FR-013) uses the platform's own test agent and the cheapest vendor
  stack, so it costs a few cents an hour while the host is awake.

## Out of scope
- Paging by phone or SMS and on-call rotations.
- Moving a live call to another worker when its worker dies (resuming calls mid-way).
- More than one realtime host, failover between hosts or regions.
- Quality and KPI digests for workspaces (a later outcome-analytics feature).
- A public status page.
