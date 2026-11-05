# Feature specification: provider resilience and capacity (015)

Created: 2026-11-05. Status: Draft.

## Why
Every call depends on three outside vendors at once: speech recognition, a language model and a
voice. Today Callwright has no plan B for any of them, and nobody knows how many calls the
platform can carry.

- **One vendor failure ends the call.** The voice worker retries the same vendor twice within
  about 5 seconds. If that fails, the call ends with `vendor_error:<kind>/<provider>`. The only
  fallback is chosen before the call starts: an agent set to Azure OpenAI runs on OpenAI when
  Azure is not configured. A vendor that is out of credit or has rejected a key is tried again on
  every new call.
- **A stalled transcription stream goes unnoticed.** If speech recognition stops returning text
  while the caller is talking, the agent just waits, and the caller hears nothing.
- **Capacity is unknown.** The benchmark harness drives one scripted call at a time with fake or
  real vendors and gates on p50 and p95 latency. There is no test with many calls at once, no
  measured cost per call in processor and memory, and no list of each vendor's concurrency limit.
- **Latency hides its tail.** Each turn stores its parts (speech final, end-of-turn wait,
  language model first token, voice first audio, tool time) and the caller-measured end-to-end
  time. The dashboard shows p50 and p95, with no p99 and no figure for time that none of the
  parts explains.
- **Long calls grow without limit.** A single-prompt agent sends the whole conversation to the
  language model on every turn. Calls can be set to last up to 60 minutes, so late turns get
  slower and more expensive. Flow agents can already summarise at a handoff, but only there.
- **Barge-in is set low.** At the default sensitivity, 0.26 seconds of caller sound with no
  words stops the agent, so a caller's "mm-hmm" can cut it off.

Callwright's latency targets for a turn (caller stops speaking to first agent audio, real
vendors): p50 under 2.0 s, p90 under 2.7 s, p99 under 3.9 s. The last real-vendor benchmark
measured p50 1.64 to 1.75 s and p95 2.13 to 2.17 s on single calls.

## User scenarios and testing

### User story 1: a vendor failure does not end the call (P1)
A caller is mid-conversation when the language model vendor starts rejecting requests. The agent
keeps talking: the request moves to the next model in the fallback chain, the caller hears at
most a slightly longer pause, and later turns go straight to the fallback while the failing
vendor rests. The same holds for speech recognition and the voice. The call's timeline shows each
switch, and a billing or auth error raises an alert (014).

**Why this priority**: an outage or an expired key at one vendor today fails every call on the
platform until someone notices.

**Independent test**: on staging, make the primary language model return "payment required" and
place 10 calls; all 10 complete, each shows one switch event, the failing vendor is not tried
again for 15 minutes, and one P1 alert is sent.

**Acceptance scenarios**:
1. **Given** an agent on model A with fallback B, **When** A returns a billing or auth error,
   **Then** the same turn is answered by B, the caller hears no error message, and A is skipped on
   every call for 15 minutes.
2. **Given** A answers "overloaded", **When** the turn is retried, **Then** B answers it, and A is
   skipped for 20 seconds, then tried with one request before it is used again.
3. **Given** A times out three times within 30 seconds, **When** the third timeout happens,
   **Then** A is skipped for 15 seconds; if it fails again after that, the pause doubles each
   time, up to 30 minutes.
4. **Given** A fails after the agent has already spoken half a reply, **When** B takes over,
   **Then** B continues from what the caller actually heard and does not repeat it.
5. **Given** the voice vendor fails, **When** the fallback voice takes over, **Then** it uses the
   closest voice for the same language and keeps it for the rest of the call.
6. **Given** every provider of one kind fails, **When** no fallback is left, **Then** the call
   ends as it does today, with the apology and reason `vendor_error:<kind>/<provider>`.

---

### User story 2: the team knows how many calls the platform can carry (P1)
An engineer runs a load test with scripted callers. Each caller plays pre-recorded lines, listens
for the agent and answers. Runs ramp up, burst, and hold long calls, first with fake vendors that
cost nothing and then with a small real-vendor run. Every 10 seconds the run captures processor,
memory, audio gaps and latency. The result is a per-call resource budget ("this host carries N
calls with 30% headroom") and a list of findings that are re-tested after each fix.

**Why this priority**: without it, no one can say when calls will start to degrade, and every
later capacity change is a guess.

**Independent test**: run the ramp profile with fake vendors to 30 concurrent calls; the report
shows the plateau processor and memory per call (p50 and p95), latency percentiles at each step
and the concurrency at which a target is first missed.

**Acceptance scenarios**:
1. **Given** a ramp profile adding 5 calls every 2 minutes, **When** the run ends, **Then** the
   report shows turn latency p50, p90 and p99 and resources per call at each step.
2. **Given** a running test, **When** the operator presses the kill switch, **Then** every test
   call ends and frees its resources within 30 seconds.
3. **Given** a running test whose turn p95 passes twice the target or whose error rate passes 5%,
   **When** that happens, **Then** the test stops by itself and says why.
4. **Given** a finished test, **When** someone opens analytics or billing, **Then** the test calls
   are marked as load tests and are not counted or charged to any customer.
5. **Given** finding 7 from round 3, **When** its fix ships, **Then** the same profile is run
   again and the finding is closed only if the result meets its target.

---

### User story 3: vendor limits are known before a release (P2)
Before a release or a capacity change, the team checks the vendor inventory: for each vendor and
plan, how many concurrent streams or requests it allows, what it does past that (refuses or
queues), and where the figure comes from. If the planned peak is above 80% of any limit, the
release gate fails and names the vendor.

**Why this priority**: a vendor limit is a capacity ceiling that a load test with fake vendors
cannot show.

**Independent test**: set a planned peak of 50 calls with a voice vendor limit of 60; the gate
fails, naming that vendor.

**Acceptance scenarios**:
1. **Given** an inventory entry verified more than 90 days ago, **When** the gate runs, **Then**
   it warns that the entry is stale.
2. **Given** the platform's concurrent-call cap is higher than a vendor allows, **When** the gate
   runs, **Then** it fails and shows the lower number.

---

### User story 4: stalled speech recognition is caught and replaced (P2)
A caller is talking, the audio arrives, but speech recognition returns nothing. After 4 seconds
of caller speech with no text (or 5 seconds of partial text with no final), the agent switches to
the next speech recognition provider, or reconnects to the same one when there is no other, and
the call continues.

**Why this priority**: a stall looks like a rude agent and is rare, but cheap to catch.

**Independent test**: inject a stall into the speech recognition stream on 20 test calls; at
least 19 recover within 6 seconds and each shows an `stt_stall` event.

**Acceptance scenarios**:
1. **Given** 4 seconds of caller speech with no text, **When** the watchdog fires, **Then** the
   stream is replaced, the event is recorded, and the agent answers the caller's next words.
2. **Given** a call that has already had 2 stall switches, **When** a third stall happens,
   **Then** the call follows the normal vendor-failure path.
3. **Given** the agent is speaking and the caller is silent, **When** the agent's own audio
   reaches the input, **Then** the watchdog does not fire.

---

### User story 5: the latency tail and the unexplained gap are visible (P2)
An operator looks at the dashboard and a call's latency view and sees p50, p90 and p99 for turns,
the time to the agent's first audio after a call is admitted, and an "unaccounted" figure: the
part of each turn not explained by speech recognition, end-of-turn wait, model, voice or tools.

**Why this priority**: p95 hides the turns that callers remember, and an unexplained gap points
at the platform rather than a vendor.

**Independent test**: on a set of 200 turns, the shown p99 matches a direct calculation, and the
unaccounted figure per turn equals end-to-end minus the sum of the parts.

**Acceptance scenarios**:
1. **Given** fewer than 100 turns in the chosen period, **When** the dashboard loads, **Then** p99
   shows "not enough data" while p50 and p90 still show.
2. **Given** a turn where the reply was prepared before the caller finished (preemptive
   generation), **When** the parts overlap, **Then** unaccounted is shown as 0 and the turn is
   marked as overlapped.

---

### User story 6: long calls stay fast (P3)
On a 40-minute call, the agent answers as quickly at minute 35 as at minute 5 and still remembers
the caller's account number from the start. After 12 caller turns, older turns fold into a
rolling summary that is updated after each reply, while the last 12 caller turns stay word for
word.

**Why this priority**: most calls are short; long calls are where the cost and slowdown show.

**Independent test**: run 45-minute scripted calls; the model's first-token time in the last 10
minutes is within 15% of the first 10 minutes, and questions about facts given in the first 5
minutes are answered correctly.

**Acceptance scenarios**:
1. **Given** a call at caller turn 20, **When** the agent answers, **Then** the model sees the
   summary plus the last 12 caller turns, and the stored transcript is still complete.
2. **Given** the caller changed their callback number at turn 5 and again at turn 15, **When** the
   summary is written, **Then** it holds only the turn-15 number.
3. **Given** the summary update fails, **When** the next turn starts, **Then** the model sees the
   full conversation as today.

---

### User story 7: a fair test of a higher barge-in bar (P3)
The team runs an A/B test on calls to agents at the default interruption setting: half keep
today's bar (0.26 seconds, no words needed), and half need at least 0.6 seconds of speech and 2
words. A third arm at 1.2 seconds and 3 words can be added. The team adopts the higher bar only if
it clearly cuts false interruptions without making real interruptions feel slow.

**Why this priority**: talk-over on short acknowledgements is a known risk, but a higher bar can
make the agent feel deaf, so it needs data first.

**Independent test**: run 200 simulated calls per arm with scripted backchannels ("mm-hmm",
"yeah", "okay") and real interruptions; the report shows false interruptions per call and stop
time for real interruptions per arm.

**Acceptance scenarios**:
1. **Given** a call in the higher-bar arm, **When** the caller says "mm-hmm" while the agent
   speaks, **Then** the agent keeps speaking.
2. **Given** a call in the higher-bar arm, **When** the caller says "no, wait, that's wrong",
   **Then** the agent stops, and the stop time is recorded.
3. **Given** an agent with a non-default interruption setting, **When** calls are assigned,
   **Then** it is never in the test.

### Edge cases
- A fallback model does not support a tool the agent uses: that model is skipped for the agent,
  and a chain left with no usable model is a warning at publish time.
- A fallback speech recognition provider has no model for the call's language (012): it is
  skipped for that call.
- A fallback voice has no close match for the language: the platform default voice for that
  language is used, and the switch event says so.
- The breaker opens in the middle of a tool call: a write tool is never repeated because of the
  switch (its result is kept); only the model's next step moves to the fallback.
- Two calls trip the same breaker at the same moment: the provider is skipped once, not twice
  as long.
- Keypad entry (DTMF) is in progress when speech recognition is switched: keypad digits keep
  being collected; they do not depend on speech recognition.
- The stall watchdog sees loud background noise but no speech: it must use speech detection, not
  loudness alone.
- A load test runs while the host is asleep: the test wakes it first and does not start calls
  until readiness says "ready" (014).
- A long-call summary must not include card numbers or security codes (017 masking applies).
- An agent set to switch language (012) mid-call: the summary keeps facts in the language they
  were given.

## Requirements

### Functional requirements

Fallback and circuit breaker
- **FR-001**: Each kind (speech recognition, language model, voice) MUST have a fallback chain:
  the agent's chosen provider first, then up to 2 platform-chosen fallbacks that support the
  agent's language and features. The platform keeps a default chain per kind; an agent can turn
  fallback off.
- **FR-002**: Time limits per attempt: speech recognition MUST connect and send its first
  response within 2.0 seconds, with one retry after 0.3 seconds; the language model MUST send its
  first token within 3 seconds, with no retry on the same provider; the voice MUST send its first
  audio within 2.0 seconds.
- **FR-003**: Each vendor error MUST be classed as billing (payment required), auth (key
  rejected, access forbidden, model not found), overloaded (rate limited, service unavailable,
  over capacity) or transient (timeouts, conflicts, dropped connections, other server errors).
- **FR-004**: A circuit breaker per provider and model, shared by every call on the host, MUST
  skip the provider for 15 minutes after a billing or auth error, for 20 seconds after an
  overloaded error, and for 15 seconds after 3 transient errors within 30 seconds. Each time it
  opens again straight after a trial, the pause MUST double, up to 30 minutes. After a pause, one
  trial request decides whether the provider is used again.
- **FR-005**: A switch inside a call MUST be silent: no error is spoken. If part of a reply was
  already spoken, the fallback MUST continue from what the caller heard.
- **FR-006**: A voice fallback MUST pick the closest voice in the same language (by the voice
  catalogue's gender first, then its other descriptors) and keep it for the rest of the call.
- **FR-007**: When every provider of a kind has failed, the call MUST end as it does today
  (apology and `vendor_error:<kind>/<provider>`).
- **FR-008**: Each switch MUST be recorded as a call event (kind, from, to, error class, time),
  shown in the call timeline, and counted per provider. Billing and auth errors MUST feed 014's
  alert rule.
- **FR-009**: Usage and cost MUST be charged for the provider that actually served each part.
- **FR-010**: A write tool that already ran MUST NOT run again because of a model switch.

Speech recognition stall watchdog
- **FR-011**: If speech is detected from the caller for 4 seconds with no text, or partial text
  arrives with no final text for 5 seconds, the stream MUST be treated as stalled and replaced by
  the next provider in the chain, or reconnected to the same provider when there is no other.
  Caller audio from the last 5 seconds MUST be sent to the new stream.
- **FR-012**: A call MUST have at most 2 stall switches; after that the normal vendor-failure path
  applies. Each switch MUST be recorded as an `stt_stall` event and counted per provider.
- **FR-013**: The watchdog MUST NOT fire while only the agent's own audio or non-speech noise is
  present.

Load test and per-call budget
- **FR-014**: A load-test tool MUST drive many scripted callers at once. Each caller plays
  pre-recorded lines and treats the agent's turn as over after 1.6 seconds of quiet. Time limits:
  15 seconds for the greeting, 20 seconds for a reply, 900 seconds for a whole call (long-call
  profile excepted). Each round uses the same test agent.
- **FR-015**: Profiles MUST include ramp (add calls in steps to a target), burst (a set number of
  calls within 10 seconds), long calls (30 minutes each) and soak (target concurrency held for 1
  hour).
- **FR-016**: The tool MUST support fake vendors with realistic delays (no vendor cost) and real
  vendors with a spend cap per run, through both the browser entry path and the phone path.
- **FR-017**: Every 10 seconds the tool MUST capture processor, memory and network per component,
  active calls, audio gaps over 150 ms, turn latency and errors.
- **FR-018**: A kill switch MUST end every test call and free its resources within 30 seconds. A
  test MUST stop by itself when turn p95 passes twice the target or errors pass 5% of turns.
- **FR-019**: Test calls MUST be marked as load tests, MUST NOT be charged to customers and MUST
  be left out of customer analytics, quality checks and issues.
- **FR-020**: Findings MUST be numbered per round, each linked to its evidence, and closed only
  after the same profile is run again and meets the target.
- **FR-021**: Each round MUST report processor and memory per concurrent call at the plateau, for
  the voice worker and for the whole realtime host: p50 for cost and p95 for sizing. It MUST state
  the number of calls the host carries with 30% headroom. These figures MUST be measured before
  any tuning and again on each release that changes the call path.
- **FR-022**: Each real-vendor round MUST report vendor cost per call minute and the share of each
  kind.

Vendor inventory and release gate
- **FR-023**: A vendor inventory MUST list, per vendor and plan: the concurrency or rate limit,
  what happens past it (refuse or queue), the source (contract, vendor documentation, measured)
  and the date it was checked.
- **FR-024**: A release gate MUST fail when the planned peak concurrency exceeds 80% of any
  vendor limit, or when the platform's concurrent-call cap exceeds the lowest limit, and MUST name
  the vendor. Entries older than 90 days MUST raise a warning.

Latency
- **FR-025**: Each turn MUST keep its parts and its end-to-end time as today, and MUST add
  "unaccounted": end-to-end minus the sum of the parts. When the parts overlap, unaccounted MUST
  be 0 and the turn MUST be marked as overlapped.
- **FR-026**: The dashboard and the call view MUST show p50, p90 and p99 for turn latency and
  unaccounted time, and the time from call admission to the agent's first audio (p50, p95 and
  maximum) across the platform and per agent.
- **FR-027**: p99 MUST be shown only with at least 100 turns, and p50 and p90 with at least 20;
  otherwise "not enough data".

Long-call compaction
- **FR-028**: For single-prompt agents, once a call passes 12 caller turns, the language model
  MUST see a rolling summary of older turns plus the last 12 caller turns word for word. The
  summary MUST be updated after the agent's reply, never while the caller waits.
- **FR-029**: The summary MUST keep facts the caller gave (names, numbers, dates), commitments
  the agent made, tool outcomes and open questions. When the caller corrects a fact, only the
  latest value MUST be kept.
- **FR-030**: If the summary is missing or older than 3 turns, the model MUST see the full
  conversation.
- **FR-031**: The stored transcript MUST stay complete. Flow agents keep their handoff strategies
  (004), and compaction applies within a long step in the same way.

Barge-in A/B test
- **FR-032**: Calls to agents at the default interruption setting that are opted into the test
  MUST be assigned at random, 50/50, to today's bar (0.26 seconds, no words) or to the higher bar
  (at least 0.6 seconds of speech and at least 2 words). A third arm (1.2 seconds, 3 words) MAY be
  added. Agents with a changed setting MUST NOT be included.
- **FR-033**: Per arm, the test MUST measure: false interruptions per call (the agent stopped and
  resumed with no caller words, or the words were a backchannel), stop time for real
  interruptions (caller starts speaking to agent audio stopping), caller repeats after
  talk-over, and turn latency.
- **FR-034**: The higher bar MUST become the default only if, over at least 200 calls per arm,
  false interruptions fall by at least 50%, stop time p50 rises by no more than 300 ms, and turn
  latency does not get worse. The result and the decision MUST be recorded.

### Key entities
- **Fallback chain**: kind, ordered providers and models, scope (platform default or agent),
  enabled.
- **Breaker state**: provider and model, state (closed, open, trial), error class, opened at,
  pause length, failures in the current window.
- **Provider switch event**: call, kind, from, to, error class, time, mid-reply or not.
- **Load-test round**: profile, vendor mode, entry path, build, captures, results, findings.
- **Finding**: number, round, description, evidence, target, status, re-test round.
- **Per-call budget**: build, component, processor and memory per call (p50, p95), calls per host
  with headroom.
- **Vendor limit**: vendor, plan, limit, behaviour past it, source, checked on.
- **Turn latency record**: the existing parts plus unaccounted and the overlap mark.
- **Call summary**: call, covers turns up to, text, updated at.
- **Barge-in experiment**: arms, assignment per call, measurements, decision.

## Success criteria

- **SC-001**: With the primary language model forced to fail (billing, auth or overloaded), every
  test call continues; the turn where the failure happens takes at most 3.5 seconds longer, and
  later turns take no longer than normal.
- **SC-002**: With a stall injected, at least 95% of calls recover within 6 seconds.
- **SC-003**: At the documented capacity, with real vendors: turn p50 under 2.0 s, p90 under
  2.7 s and p99 under 3.9 s; language model first token p50 under 0.85 s; first agent audio at
  most 1.7 s; audio gaps over 150 ms in no more than 0.5% of agent audio.
- **SC-004**: The per-call budget is published, with the target at or below 0.25 processor cores
  and 0.3 GiB of memory per call for the whole realtime host.
- **SC-005**: The release gate runs before every release that changes capacity, and no release
  ships with planned peak above 80% of a vendor limit.
- **SC-006**: Unaccounted time per turn has a p50 under 150 ms on the benchmark call set.
- **SC-007**: On 45-minute test calls, first-token time in the last 10 minutes is within 15% of the
  first 10 minutes, and at least 95% of questions about facts from the first 5 minutes are
  answered correctly.
- **SC-008**: The barge-in test reaches its sample size, and a recorded decision exists within 4
  weeks of starting.

## Assumptions
- The platform holds working keys for at least two providers of each kind among those Callwright
  already supports (for example OpenAI, Azure OpenAI and Anthropic for the model; Deepgram,
  AssemblyAI and Sarvam for speech recognition; ElevenLabs, Cartesia and Fish Audio for the
  voice).
- Workspaces do not bring their own vendor keys; breakers are platform-wide on the single host.
- Breaker state lives with the voice worker on the host and is not shared across hosts (there is
  one).
- A voice change mid-call is better than silence; callers may notice it.
- Load tests run on a staging copy or on the hosted realtime host in a maintenance window, never
  during customer calls.
- The existing single-call benchmark harness, its scripted caller and fake vendors are the
  starting point for the load-test tool.
- The 3-second first-token limit suits the voice models Callwright offers; a reasoning model that
  needs longer is a configuration warning, not a reason to raise the limit for everyone.
- Text simulations (008) keep using a single model; fallback applies to live calls.

## Out of scope
- Moving a call to another worker when its worker dies.
- More than one realtime host and autoscaling.
- Self-hosted speech or language models.
- Workspace-owned vendor keys and per-workspace breakers.
- Turn-taking changes other than the barge-in bar (end-of-turn timing is already faster than the
  targets need).
