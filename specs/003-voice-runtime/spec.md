# Feature Specification: Voice Runtime

**Feature Branch**: `003-voice-runtime`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "The voice worker and the call write side. Browser test calls with dynamic variables, a speech pipeline assembled from an immutable agent version (voice activity detection, speech-to-text, LLM, text-to-speech, noise cancellation, each vendor behind an adapter), turn-taking controls, end on silence, maximum duration, voicemail detection, keypad input, background audio, pronunciation replacement, per-turn latency and usage metering, the call lifecycle and disconnect reasons, call recording, the post-call processing pipeline, signed customer webhooks with retries, concurrency and credit checks at call start, and an offline scripted-caller harness. Tool, knowledge and flow execution are provided by other features through defined extension points."

## Clarifications

### Session 2026-10-16

- Q: Can operators turn off call recording (per workspace or per agent) in v1, and are transcripts still kept when they do? → A: Yes. A workspace-level default (on) with a per-agent override (inherit, on, off). When the effective setting is off, no recording is started, recording links return a clear "not recorded" state, and transcripts, latency and usage metrics are still stored. The effective setting is resolved at call admission and stored on the call as `recording_enabled`. The workspace default is owned by 001 (workspace settings) and the agent override by 002 (AgentConfig).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Talk to an agent from the browser (Priority: P1)

An operator building an agent clicks "Test call". If the agent's prompt or greeting uses
variables (for example `{{customer_name}}`), a dialog lists each one, pre-filled with the agent's
default value, and the operator can override any of them. The browser connects, the agent speaks
first or waits for the caller depending on its configuration, and the operator sees the agent's
state (connecting, listening, thinking, speaking) and a live transcript labelled "You" and
"Agent". Clicking "End call" hangs up. The call then appears in call history with its transcript,
recording (or "not recorded" when recording is off), cost and per-turn latency.

**Why this priority**: This is the first moment an operator hears their agent. Every other
runtime behaviour is verified through this path before any phone number exists.

**Independent Test**: With a published or draft agent and a funded workspace, start a test call,
exchange three turns, end the call, and confirm a call record exists with channel "web", status
"ended", disconnect reason "user_hangup", a transcript entry for every turn and a latency
breakdown for each agent reply. (Pricing, recording and the move to "completed" are verified
in User Story 4.)

**Acceptance Scenarios**:

1. **Given** an agent whose greeting is "Hi {{customer_name}}" with default "there", **When**
   the operator enters "Priya" and starts a call, **Then** the agent says "Hi Priya" within
   3 seconds of the connection completing.
2. **Given** an agent set so the caller speaks first, **When** the call connects, **Then** the
   agent stays silent until the caller speaks.
3. **Given** an agent set so the agent speaks first with an empty greeting, **When** the call
   connects, **Then** the agent produces an opening line from its prompt.
4. **Given** a test call in progress, **When** the operator saves new prompt changes, **Then** the
   live call keeps the configuration it started with and the next test call uses the new one.
5. **Given** a test call, **When** the operator closes the browser tab without clicking
   "End call", **Then** the call ends within 15 seconds with reason "user_hangup".
6. **Given** a browser that receives a call token but never connects, **When** 60 seconds pass,
   **Then** the call is marked failed with a diagnostic explaining the caller never joined, and
   it stops counting against the workspace's concurrent-call limit.

---

### User Story 2 - Calls start only when allowed and always end cleanly (Priority: P1)

Before any call starts, on any channel, the system checks that the account's email is verified,
the workspace has credit and is under its concurrent-call limit, and the agent's configuration is
fully priced. A refused call is still recorded with a clear reason. Once running, a call always
reaches a final state with exactly one disconnect reason, whether the caller hangs up, the agent
ends it, the conversation goes silent, the maximum duration is reached, credit runs out or
something fails.

**Why this priority**: Calls cost real money per second. Running a call the workspace cannot pay
for, or leaving a call open forever, is a direct financial loss and a trust failure.

**Independent Test**: Set a workspace's concurrency limit to 1, start one call, attempt a second
and confirm it is refused with reason "concurrency_limit"; set balance to zero and confirm a new
call is refused with "insufficient_credit"; run a call past its maximum duration and confirm it
ends with "max_duration_reached".

**Acceptance Scenarios**:

1. **Given** a workspace at its concurrency limit, **When** a new call is requested, **Then** it
   is refused before any audio is exchanged, the requester sees "concurrency limit reached", and
   a call record with status "failed" and reason "concurrency_limit" is stored.
2. **Given** a balance of $0.00, **When** a call is requested, **Then** it is refused with reason
   "insufficient_credit" and a message asking to add funds.
3. **Given** a running call whose cost pushes the balance below the allowed grace amount,
   **When** the threshold is crossed, **Then** the agent ends the call within 5 seconds with
   reason "insufficient_credit".
4. **Given** an agent with end-on-silence set to 30 seconds, **When** neither side speaks for 30
   seconds, **Then** the call ends with reason "inactivity".
5. **Given** an agent with maximum duration 2 minutes, **When** the call reaches 2 minutes,
   **Then** it ends within 5 seconds with reason "max_duration_reached".
6. **Given** the process running a call stops responding, **When** 60 seconds pass without a
   heartbeat, **Then** the call is closed with reason "error", is billed only for the time it was
   connected, and its concurrency slot is released.
7. **Given** an agent configuration that names a speech or language vendor the platform does not
   support, **When** a call is requested, **Then** it is refused with a message naming the
   unsupported vendor.

---

### User Story 3 - The agent sounds and behaves the way it was configured (Priority: P1)

Every setting an operator chooses in the agent builder changes what callers hear: the speech
recognition, language model and voice vendors and models; the language; voice speed; noise
cancellation; how easily the caller can interrupt; how quickly the agent replies after the caller
stops; background ambience; and pronunciation fixes (for example "SQL" spoken as "sequel"). All of
these come from one frozen agent version so a call is reproducible later.

**Why this priority**: The value of a voice agent is how it sounds and how naturally it takes
turns. Configuration that does not change behaviour makes the builder meaningless.

**Independent Test**: Run the same scripted caller against two versions of one agent that differ
only in responsiveness (0.2 vs 0.9) and confirm the measured wait after end of caller speech is
longer for 0.2; run an agent with a pronunciation entry and confirm the spoken text uses the
replacement while the transcript shows the original word.

**Acceptance Scenarios**:

1. **Given** interruption sensitivity 0.95, **When** the caller says two or more words while the
   agent is talking, **Then** the agent stops speaking within 300 ms and the transcript marks the
   agent's turn as interrupted, keeping only the words actually spoken.
2. **Given** interruption sensitivity 0, **When** the caller talks over the agent, **Then** the
   agent finishes its sentence.
3. **Given** a pronunciation entry "SQL" to "sequel", **When** the agent's reply contains "SQL" or
   "sql", **Then** the voice says "sequel" and the stored transcript says "SQL".
4. **Given** background audio "office ambience" at 80% volume, **When** the call connects,
   **Then** the caller hears continuous ambience under the agent's voice for the whole call.
5. **Given** a speech-to-text model with built-in end-of-turn detection, **When** the call runs,
   **Then** that model's turn signal is used; otherwise a semantic end-of-turn model is used.
6. **Given** an agent version created yesterday and edited today, **When** a call that ran on
   yesterday's version is inspected, **Then** it shows yesterday's version identifier and the
   vendors and models that version used.

---

### User Story 4 - Every finished call is recorded, priced and processed in order (Priority: P2)

When a call ends, the platform finalizes the transcript, prices the call and charges the
workspace, runs analysis and quality checks (provided by other features), notifies the customer,
and marks the call completed. Each step runs once even if it is retried. A two-channel recording
(agent and caller on separate channels) is stored for every connected call whose effective
recording setting is on. Operators can turn recording off for the whole workspace or for one
agent; such calls keep their transcript, metrics and cost but have no audio.

**Why this priority**: Call history, billing, evaluation and webhooks all depend on this
pipeline. It can follow P1 because live calls work without it, but billing is wrong until it
lands.

**Independent Test**: End a call, then replay every pipeline step twice; confirm exactly one
charge transaction, one "call_analyzed" notification, status "completed", and a playable
recording linked to the call.

**Acceptance Scenarios**:

1. **Given** a call that connected for 4.2 seconds, **When** it is processed, **Then** it is
   billed as 5 seconds and the time spent ringing is not billed.
2. **Given** the pricing step fails transiently, **When** it is retried, **Then** the call is
   charged exactly once.
3. **Given** the analysis step fails after all retries, **When** the pipeline continues, **Then**
   the call is still charged, the customer is notified with the failed step listed, and the call
   is marked completed with a processing warning.
4. **Given** recording upload fails, **When** the call is processed, **Then** the call is still
   priced and completed, and the call shows "recording unavailable".
5. **Given** a call that never connected (busy, no answer, refused), **When** it ends, **Then** no
   charge is made and only a "call_ended" notification is sent.
6. **Given** a workspace with recording on by default and an agent whose recording override is
   "off", **When** a call to that agent connects and ends, **Then** no recording is started, the
   call shows "not recorded" (not "recording unavailable"), its transcript, latency and cost are
   stored, it is marked completed without a processing warning, and `call_analyzed` carries no
   recording link and the "not recorded" state.
7. **Given** a workspace with recording off by default, **When** a call runs on an agent whose
   override is "inherit", **Then** it is not recorded; **When** a call runs on an agent whose
   override is "on", **Then** it is recorded.

---

### User Story 5 - Customers receive signed call events at their own endpoint (Priority: P2)

An operator puts a webhook URL on an agent. Their system receives `call_started`, `call_ended`
and `call_analyzed` events for every call of that agent, each signed so they can prove it came
from Callwright and is fresh. Failed deliveries are retried on a schedule, every attempt is
visible in a delivery log, and any delivery can be re-sent by hand.

**Why this priority**: Most production customers integrate through webhooks (CRM updates, ticket
creation), but the product is usable without them.

**Independent Test**: Point an agent at a test endpoint that fails twice then succeeds; place a
call; confirm three deliveries for "call_analyzed" in the log, the third successful, each carrying
a signature that verifies with the workspace secret.

**Acceptance Scenarios**:

1. **Given** an agent with a webhook URL, **When** a call connects, ends and finishes processing,
   **Then** the endpoint receives `call_started`, `call_ended` and `call_analyzed` with the call
   identifier, agent, version, channel, numbers, timestamps, status and (for the last two)
   disconnect reason, transcript and cost.
2. **Given** an endpoint that takes longer than the agent's webhook timeout, **When** a delivery
   is attempted, **Then** the attempt is recorded as timed out and retried.
3. **Given** an endpoint that returns 400, **When** a delivery is attempted, **Then** it is not
   retried and is marked failed with the response code.
4. **Given** a rotated signing secret, **When** events are sent in the next 24 hours, **Then** they
   carry signatures for both the new and previous secret.
5. **Given** a webhook URL pointing at a private network address, **When** the agent is saved or
   an event is sent, **Then** the delivery is blocked and the reason is shown.
6. **Given** a webhook URL, **When** the operator clicks "Send test event", **Then** a signed
   `ping` event is sent and the response code and time are shown.

---

### User Story 6 - Voicemail and keypad input are handled (Priority: P2)

On outbound calls with voicemail detection on, the agent recognises an answering machine within
the first 30 seconds and either hangs up or waits for the greeting to finish and leaves the
configured message. With keypad input on, digits the caller presses are collected until the
termination key, the digit limit or a pause, and passed to the agent as one caller turn.

**Why this priority**: Required for outbound campaigns and IVR-style flows, but not for the first
inbound or browser use.

**Independent Test**: In the offline harness, script an answering-machine greeting followed by a
beep and confirm the agent leaves the configured message after the beep and the call ends with
reason "voicemail_reached"; script keypad presses "1234#" and confirm one caller turn "1234".

**Acceptance Scenarios**:

1. **Given** voicemail action "hang up", **When** an answering machine is detected, **Then** the
   call ends with reason "voicemail_reached" and final status "voicemail".
2. **Given** voicemail action "leave message", **When** the greeting ends, **Then** the agent
   speaks the message once, hangs up, and the call is billed for its connected time.
3. **Given** keypad input with termination key "#" and 10 digits, **When** the caller presses
   "5551234#", **Then** the agent receives "5551234" as one turn.
4. **Given** keypad input with a 2.5 second timeout, **When** the caller presses "42" and stops,
   **Then** the agent receives "42" 2.5 seconds after the last press.

---

### User Story 7 - Engineers can test the runtime without phones or vendors (Priority: P3)

A platform engineer writes a scripted caller (what the caller says, when they interrupt, when they
go silent, which keys they press, what the agent must say or do) and runs it against any agent
configuration on a laptop or in CI, with no telephony and, by default, no vendor network calls.
The same scripts, run against real vendors, form the latency benchmark that every hot-path change
must pass.

**Why this priority**: It protects every other story from regressions and enforces the latency
budget, but customers never see it directly.

**Independent Test**: Run the harness suite on a machine with no network; all scenarios pass in
under 5 minutes. Run the benchmark mode and receive p50 and p95 turn latency compared with the
stored baseline.

**Acceptance Scenarios**:

1. **Given** a script where the caller is silent for 31 seconds and end-on-silence is 30 seconds,
   **When** it runs, **Then** the harness reports the call ended with "inactivity".
2. **Given** a change that raises benchmark p95 turn latency above 1500 ms or p50 above 800 ms on
   the default stack, **When** the benchmark runs, **Then** it fails and reports the regression.

---

### Edge Cases

- The caller and the agent talk at the same moment the agent finishes: no duplicate reply; the
  agent's next reply starts only after the caller's turn ends.
- A dynamic variable referenced in the prompt has no value and no default: it renders as empty,
  the call proceeds, and the call record lists the missing variable name.
- A caller tries to override a built-in variable (for example `call_id`): the override is
  ignored and the call record notes it.
- A vendor stream drops mid-call: the adapter retries; if it cannot recover within 5 seconds the
  call ends with reason "error" and the failing vendor is recorded.
- A pronunciation entry matches part of a longer word ("SQL" inside "MySQL"): only whole-word
  matches are replaced.
- Two pipeline runs for the same call race: one wins per step; the other is a no-op.
- The agent version referenced by a running call is deleted from the builder: versions are
  immutable and cannot be deleted while any call references them.
- Background audio file is missing or unreadable: the call continues without ambience and a
  warning is recorded on the call.
- A customer webhook endpoint keeps failing: after the last retry the delivery is marked failed;
  the call itself is unaffected.
- The webhook URL resolves to a public address at save time and a private one at send time: the
  send is blocked.
- End-on-silence and maximum duration both trigger in the same second: the earlier timer wins
  and the reason reflects it.
- Keypad input arrives while the agent is speaking: digits are collected and treated as an
  interruption only if interruption sensitivity is above 0.
- The workspace recording default or an agent's recording override changes while a call is
  running: the running call keeps the setting resolved at its admission; the change applies to
  the next call.
- A call with recording off is fetched for playback or download: the response states "not
  recorded" and offers no link; this is distinct from "recording unavailable" (a failed
  recording on a call that should have been recorded).

## Requirements *(mandatory)*

### Functional Requirements

**Starting calls**

- **FR-001**: System MUST let an authenticated operator start a browser test call for an agent,
  choosing the current draft (default), the published version, or a specific version, and
  passing values for the agent's dynamic variables.
- **FR-002**: System MUST return, for a browser test call, a short-lived credential that lets
  only that browser join only that call's audio session, valid for joining for 15 minutes.
- **FR-003**: System MUST freeze the exact agent version for every call at start and run the
  whole call from that version, unaffected by later edits.
- **FR-004**: Calls on live channels (phone, WhatsApp, outbound) MUST use the agent's published
  version; if none exists the call is refused with "agent not published".
- **FR-005**: System MUST resolve dynamic variables in this order: value supplied for the call,
  then the agent's default, then empty; MUST provide built-in variables (`call_id`, `channel`,
  `direction`, `user_number`, `agent_number`, `timezone`, `current_time`, `current_date`,
  `current_datetime`) that callers cannot override; and MUST record any missing names.
- **FR-006**: System MUST validate supplied variables: names start with a letter or underscore
  and contain only letters, digits and underscores (max 64 characters); at most 50 variables;
  each value at most 2,000 characters.
- **FR-007**: Before any call starts on any channel, System MUST check, in this order: account
  email verified, agent version resolvable, every vendor in the version supported and priced,
  workspace balance above zero, and active calls below the workspace concurrency limit. The
  concurrency check and the call creation MUST be atomic so two simultaneous requests cannot both
  take the last slot.
- **FR-008**: System MUST record every refused call with status "failed" and the matching reason
  (`insufficient_credit`, `concurrency_limit` or `error` with a diagnostic) and return that
  reason to the requester.
- **FR-009**: System MUST expose a single admission capability that other channels (phone
  numbers, WhatsApp, outbound calling) reuse, accepting a channel, direction, numbers, variables,
  an inbound-routing result and an idempotency key.

**Running calls**

- **FR-010**: System MUST assemble each call's speech pipeline (voice activity detection,
  speech-to-text, language model, text-to-speech, noise cancellation) from the agent version,
  selecting each vendor through an interchangeable adapter; adding a vendor MUST NOT require a
  change to stored data shapes.
- **FR-011**: System MUST honour start speaker: agent first speaks the greeting verbatim (with
  variables filled in) or, if the greeting is empty, a model-generated opening; caller first
  waits for the caller.
- **FR-012**: System MUST map interruption sensitivity (0 to 1) to how much caller speech
  interrupts the agent, monotonically, where 0 means the agent cannot be interrupted and higher
  values interrupt sooner; an interrupted agent stops within 300 ms and its transcript turn is
  truncated to what was actually spoken and flagged.
- **FR-013**: System MUST map responsiveness (0 to 1) to the wait after the caller stops
  speaking before the agent replies, monotonically, where higher values reply sooner.
- **FR-014**: System MUST use a speech-to-text model's own end-of-turn signal when the model
  provides one, and a semantic end-of-turn model otherwise.
- **FR-015**: System MUST end a call with reason `inactivity` after the configured silence period
  (10 to 300 seconds) in which neither party speaks and the agent is not working on a reply.
- **FR-016**: System MUST end a call with reason `max_duration_reached` within 5 seconds of the
  configured maximum (30 to 3,600 seconds), measured from connection.
- **FR-017**: For inbound phone and WhatsApp calls, System MUST let the call ring for the
  configured ring duration before the agent answers.
- **FR-018**: System MUST replace pronunciation dictionary words (whole word, case-insensitive)
  in text sent to the voice, without changing the stored transcript.
- **FR-019**: System MUST play configured background ambience (a built-in sound or an uploaded
  file) at the configured volume for the whole connected call.
- **FR-020**: System MUST apply the configured noise cancellation to the caller's audio before
  speech recognition, or none when set to off.
- **FR-021**: When keypad input is enabled, System MUST collect caller digits until the
  termination key, the configured digit count (1 to 99) or the configured pause (1 to 10
  seconds), and deliver them to the agent as one caller turn.
- **FR-022**: When voicemail detection is enabled on an outbound call, System MUST classify the
  answer as human or machine within the first 30 seconds; on machine, either end the call or wait
  for the greeting to finish, speak the configured message (max 500 characters) once and end;
  in both cases the disconnect reason is `voicemail_reached` and the final status `voicemail`.
- **FR-023**: System MUST let the caller end the call by hanging up (reason `user_hangup`) and
  let agent logic end it (reason `agent_hangup`), and MUST offer other features a call-control
  capability (end call with reason, speak a message, send keypad tones, report tool and flow
  activity) without exposing vendor details.
- **FR-024**: System MUST offer extension points for other features to supply callable tools
  and knowledge retrieval for a call, and to drive a call by a conversation flow, both chosen from
  the agent version; without those features installed, single-prompt agents run with no tools
  and flow agents are refused with a clear message.
- **FR-025**: During a call, System MUST check accumulated cost against the workspace balance at
  least every 15 seconds and end the call with `insufficient_credit` when the balance minus
  running cost falls below the negative grace amount set by the platform.
- **FR-026**: System MUST end any call whose runtime has not reported for 60 seconds with reason
  `error`, and MUST mark any call not picked up by a runtime within 60 seconds of creation as
  failed.

**Lifecycle, metering and records**

- **FR-027**: Calls MUST follow the lifecycle `queued`, `ringing`, `in_progress`, `ended`,
  `processing`, `completed`, with terminal alternatives `failed`, `no_answer`, `busy` and
  `voicemail`; every call that ends MUST carry exactly one disconnect reason from:
  `user_hangup`, `agent_hangup`, `call_transfer`, `voicemail_reached`, `inactivity`,
  `max_duration_reached`, `error`, `concurrency_limit`, `insufficient_credit`. Calls that never
  connected (busy, no answer) carry no disconnect reason.
- **FR-028**: For every agent reply that follows caller speech, System MUST store: time from end
  of caller speech to final transcript, end-of-turn decision delay, language model time to first
  token, voice time to first audio, and end-to-end time from end of caller speech to first agent
  audio; and, for the opening line, time from connection to first agent audio.
- **FR-029**: System MUST meter, per call and per vendor, speech-to-text audio seconds, language
  model input, cached-input and output tokens, voice characters, and noise-cancellation seconds,
  and store them with the call.
- **FR-030**: System MUST store the full transcript as ordered items: caller and agent messages
  (with interrupted flag and recognition confidence), tool calls and results, flow transitions
  and keypad turns, each with its time offset from connection.
- **FR-031**: Billable duration MUST run from connection to end, rounded up to the whole second;
  ringing and queue time MUST NOT be billed.
- **FR-032**: System MUST record a two-channel recording (agent and caller separate) of every
  connected call whose effective recording setting is on, stored encrypted, and link it to the
  call; a failed recording MUST NOT block processing.
- **FR-043**: System MUST resolve each call's effective recording setting once, at admission,
  from the agent version's recording override (`inherit`, `on`, `off`) and, for `inherit`, the
  workspace's recording default (on unless changed); MUST store the result on the call
  (`recording_enabled`) and MUST NOT change it for the rest of the call.
- **FR-044**: When a call's effective recording setting is off, System MUST NOT start any audio
  recording for it, MUST mark its recording state "not recorded", MUST return that state (with
  no link) wherever a recording link is requested, including webhook events, and MUST still store
  the transcript, per-turn latency, usage meters and cost exactly as for a recorded call.

**Post-call pipeline**

- **FR-033**: When a call ends, System MUST run these steps in order: finalize transcript and
  latency statistics; price the call and charge the workspace; summary, sentiment and analysis
  variables; enabled evaluators; send the `call_analyzed` event; mark completed (or `voicemail`
  for voicemail calls). Each step MUST be idempotent per call and step.
- **FR-034**: Transcript and pricing steps MUST block later steps until they succeed (with
  retries and an operator alert after the last retry); analysis and evaluator failures MUST be
  recorded and MUST NOT block charging, notification or completion.
- **FR-035**: Calls that never connected MUST skip charging, analysis and evaluation and send
  only `call_ended`.

**Customer webhooks**

- **FR-036**: System MUST send `call_started` (on connection), `call_ended` (on end, including
  calls that never connected) and `call_analyzed` (after processing) to the agent version's
  webhook URL, if set, with the call's identifier, agent, version, channel, direction, numbers,
  timestamps, status, disconnect reason, and for `call_analyzed` the transcript, summary,
  sentiment, analysis variables, cost breakdown, latency statistics, the recording state and a
  time-limited recording link (no link when the call was not recorded).
- **FR-037**: Each delivery MUST be signed with the workspace's secret over a timestamp and the
  exact body, so receivers can verify origin and reject replays older than 5 minutes; the secret
  is shown in full only when created or rotated, and the previous secret keeps signing for 24
  hours after rotation.
- **FR-038**: A delivery succeeds on any 2xx response within the agent's webhook timeout (1 to 30
  seconds, default 3). Timeouts, connection errors, 408, 429 and 5xx MUST be retried 5 times
  (after about 10 seconds, 1 minute, 5 minutes, 30 minutes and 2 hours); other responses fail
  without retry.
- **FR-039**: System MUST keep a delivery log (event, call, URL, attempts with time, response
  code, duration, error and the first 1 KB of the response body) for 30 days, and let operators
  re-send any delivery and send a signed test event to a URL.
- **FR-040**: System MUST refuse to deliver to non-HTTPS URLs outside development environments
  and to addresses in private, loopback, link-local or cloud metadata ranges, checked at send
  time.

**Testing harness**

- **FR-041**: System MUST provide an offline harness that runs a scripted caller (utterances,
  pauses, interruptions, silence, keypad digits, answering-machine audio) against any agent
  configuration without telephony or vendor network access, and asserts on agent speech, tool
  calls, flow transitions, disconnect reason and timing.
- **FR-042**: The harness MUST have a benchmark mode that runs a fixed call set against real
  vendors on the default stack and reports p50 and p95 end-to-end turn latency against a stored
  baseline.

### Key Entities

- **Call**: one conversation on any channel; agent and frozen version, channel, direction,
  numbers, status, timestamps (created, ringing, connected, ended), disconnect reason,
  diagnostic, variables used and missing, transcript, usage meters, latency statistics,
  effective recording setting (resolved at admission), recording reference and state (including
  "not recorded"), processing state, and fields later filled by pricing and
  analysis.
- **Call Event**: one timestamped fact reported by the runtime during a call: a turn with its
  latency breakdown, a usage meter snapshot, a status change, a tool call, a flow transition, a
  keypad turn, a heartbeat or an error. Ordered and de-duplicated per call.
- **Processing Step**: the state of one post-call step for one call (pending, running, done,
  failed, skipped), attempt count and last error.
- **Webhook Signing Secret**: per-workspace secret (and previous secret during rotation) used to
  sign events; stored encrypted.
- **Webhook Delivery**: one event destined for one URL, with its attempts and final state.
- **Harness Script**: a scripted caller and expectations, kept with the runtime's tests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the default stack benchmark set, end-to-end turn latency is at most 800 ms at
  p50 and at most 1,500 ms at p95.
- **SC-002**: 100% of agent replies that follow caller speech have a stored latency breakdown,
  and 100% of connected calls have usage meters for every vendor they used.
- **SC-003**: For browser test calls, 95% of operators hear the greeting within 3 seconds of
  the connection completing.
- **SC-004**: In automated tests, no call is admitted when the workspace is at its concurrency
  limit or has a zero balance, including under 50 simultaneous requests for the last slot.
- **SC-005**: No call runs more than 5 seconds past its maximum duration or silence limit.
- **SC-006**: Replaying every post-call step for 100 calls produces zero duplicate charges and
  zero duplicate `call_analyzed` deliveries.
- **SC-007**: 95% of calls reach "completed" within 2 minutes of ending, excluding time spent
  waiting on the customer's webhook endpoint.
- **SC-008**: 99% of first webhook delivery attempts start within 5 seconds of the event, and a
  receiver following the published verification steps validates 100% of genuine deliveries.
- **SC-009**: The offline harness suite runs in under 5 minutes in CI with no network access.
- **SC-010**: 100% of calls whose effective recording setting is off have no recording started
  and no stored audio, while 100% of them that connected still have a transcript, latency
  breakdown and usage meters.

## Assumptions

- Agent configuration, its schema, defaults and versioning are provided by feature 002; this
  feature only reads frozen versions. A draft test call asks 002 for a version snapshot of the
  draft (reused if unchanged) without publishing it.
- Pricing rules, the ledger, balance, concurrency limit, the mid-call grace amount and the
  email-verified flag come from feature 001.
- Vendor accounts are owned by the platform in v1; customers do not bring their own vendor keys.
- Phone, WhatsApp and outbound channels (feature 010) reuse this feature's admission, lifecycle,
  metering and pipeline; this feature delivers the browser channel end to end.
- Tool execution, knowledge retrieval and transfer (005) and flow execution (004) plug into the
  extension points defined here; analysis and evaluators (007) plug into the pipeline steps.
- Browser test calls are billed like any other call.
- Recording is on by default. The workspace recording default (on or off, default on) is a
  workspace setting owned by feature 001; the per-agent override (`inherit`, `on`, `off`,
  default `inherit`) is part of the AgentConfig owned by feature 002 and is frozen with each
  version. This feature reads both at admission and does not edit them. Turning recording off
  never removes transcripts or metrics.
- Webhooks are configured per agent (URL and timeout live in the agent version); there is no
  per-event subscription filter in v1.
- The recording link inside webhook events is valid for 10 minutes; receivers fetch a fresh
  link through the calls API when needed.
- A public, unauthenticated marketing demo call is out of scope for this feature.
