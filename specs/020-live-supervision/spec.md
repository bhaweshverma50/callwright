# Feature Specification: Live supervision (020)

**Feature Branch**: `020-live-supervision`
**Created**: 2026-11-05
**Status**: Draft
**Input**: Let a person supervise live calls. Ship text-only supervision first: private whispers
that steer the agent for about 6 turns and carry bans, and approval tiers per action with approval
cards, fixed agent lines and a callback fallback. Then a rules-based "needs you" banner, live
per-line checks that never block the call and policy assist cards. Then listening, taking over and
handing back, supervisor work states and human-help metrics. Audit every intervention.

## Why

Today a person can only watch. The "Live now" card and the pinned rows on Call History poll the
calls on air every 3 seconds and show the last line; opening a call shows its live transcript.
There is no way to steer the agent, approve a risky action, step in or even be told that a call
needs attention. Caller sentiment and quality checks run only after the call ends (007).

Teams that put an agent in front of real customers want a person in the loop for the moments that
matter: a large refund, an upset caller, a request for a human. Supervision also makes it safe to
give agents more powerful actions, because the riskiest ones wait for a person.

Phasing: Phase 1 is text only (whisper, approvals, audit) and needs no new audio path. Phase 2
adds signals that tell the supervisor where to look. Phase 3 adds audio and team workflow.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Whisper private guidance to the agent (Priority: P1, Phase 1)

While a call is live, the supervisor types a whisper in the call's live view, for example "Offer
the 10% loyalty discount, don't mention the cancellation fee". The agent follows it from its next
reply for about 6 turns. The caller never hears it. Phrases like "don't mention X" or "never
offer Y" become bans that hold for the rest of the call.

**Why this priority**: Steering by text is the cheapest useful intervention: no audio, no
handover, and the caller notices nothing.

**Independent Test**: On a browser test call, send a whisper with one instruction and one ban,
and confirm the next reply follows the instruction, the ban shows as a chip, the whisper expires
after 6 agent turns, and the call's supervision timeline lists it.

**Acceptance Scenarios**:

1. **Given** a live call, **When** the supervisor sends a whisper, **Then** it shows in the live
   view as "Active, 6 turns left" and applies to the next agent reply that starts at least 1
   second later.
2. **Given** a whisper containing "don't mention the cancellation fee", **When** it is typed,
   **Then** a ban chip "Cancellation fee" appears before sending and can be removed.
3. **Given** an active ban, **When** an agent reply mentions the banned subject, **Then** the
   reply is flagged as a ban breach in the live view and the audit.
4. **Given** the caller asks "is someone else telling you what to say?", **When** the agent
   answers, **Then** it does not quote or read out the whisper.
5. **Given** an active whisper, **When** the supervisor edits or cancels it, **Then** the change
   applies from the next reply and both versions are kept in the audit.
6. **Given** a whisper sent with "Rest of call", **When** 6 turns pass, **Then** it stays active.

---

### User Story 2 - Approve risky actions before the agent takes them (Priority: P1, Phase 1)

For each agent, the operator sets a tier per action (each attached tool and each built-in call
control): allowed, allowed and notify, needs approval, or never. When the agent decides to take
an action that needs approval, it says a fixed holding line and an approval card appears for
supervisors with Approve, Deny and Handled, and a 45-second countdown. The agent then says the
fixed line for the outcome. If nobody answers twice, a critical alert is raised and the agent
offers the caller a callback.

**Why this priority**: Approvals let teams give agents real actions (refunds, cancellations,
account changes) without trusting the model alone.

**Independent Test**: Set `issue_refund` to "needs approval", ask for a refund on a test call, and
check each path: approve (the tool runs), deny (it doesn't), handled (it doesn't, and the agent
says it is done), and two timeouts (critical alert and callback offer).

**Acceptance Scenarios**:

1. **Given** `issue_refund` set to "needs approval", **When** the agent calls it with amount 250
   and order 1234, **Then** the tool does not run, the agent says the pending line ("Let me check
   that with a colleague, one moment."), and a card shows "Refund 250.00 for order 1234", the
   caller's last 3 lines and a 45 s countdown.
2. **Given** a pending card, **When** the supervisor presses Approve, **Then** the tool runs, the
   agent says the approved line and continues with the tool's result.
3. **Given** a pending card, **When** the supervisor presses Deny, **Then** the tool never runs and
   the agent says the denied line and offers what it can do instead.
4. **Given** a pending card, **When** the supervisor presses Handled, **Then** the tool does not
   run and the agent says the handled line ("That's been taken care of for you.").
5. **Given** no answer within 45 s, **When** the timer ends, **Then** the agent says the timeout
   line, the card stays open for a second 45 s, and the call's banner turns amber.
6. **Given** no answer in the second 45 s, **When** it ends, **Then** a critical alert is raised,
   the action is cancelled, and the agent offers a callback; if the caller accepts, a callback is
   booked (011) with a note naming the pending action.
7. **Given** an action set to "allowed and notify", **When** the agent takes it, **Then** it runs
   at once and a notice appears on the live call without any button to press.
8. **Given** an action set to "never", **When** a call starts, **Then** the agent cannot take that
   action on the call.

---

### User Story 3 - See a "needs you" banner on calls that need a person (Priority: P2, Phase 2)

Each live call carries a banner level: none, amber or red, set by rules, not by AI. Red when the
caller asks for a human (negations like "I don't need a person" don't count), when the caller's
mood is very low, when a ban is breached or when an approval times out twice. Amber for a low
mood, 3 live check misses or a first approval timeout. A level clears only when the signal has
recovered by a margin, so the banner does not flicker.

**Why this priority**: A supervisor cannot read every transcript; the banner says where to look.
It needs Phase 2's live checks for mood and misses.

**Independent Test**: Replay scripted calls through the live rules: "can I talk to a real
person?", "no, I don't need a manager", a mood trace that hovers around −45, and confirm the levels
and that the hovering trace changes level at most once.

**Acceptance Scenarios**:

1. **Given** the caller says "let me speak to a human", **When** the line ends, **Then** the
   banner turns red with "Caller asked for a person" and the line quoted.
2. **Given** the caller says "I don't want a manager, just fix it", **When** the line ends,
   **Then** no human-request reason is raised.
3. **Given** the mood score falls to −46, **When** the line ends, **Then** the banner turns amber;
   it clears only when the score rises above −35.
4. **Given** the mood score falls to −66, **When** the line ends, **Then** the banner turns red; it
   drops to amber only when the score rises above −55.
5. **Given** a red banner, **When** the supervisor presses "I'm on it", **Then** it stops pulsing,
   shows who acknowledged it, and the acknowledgement is audited.
6. **Given** several calls live, **When** the Live page loads, **Then** red calls sort first, then
   amber, then the rest by start time.

---

### User Story 4 - Live per-line checks that never block the call (Priority: P2, Phase 2)

With live checks on for an agent, each line is checked while the call goes on: a short QA
checklist, a fact check of the agent's claims against what its tools and knowledge base
returned on this call, an on-track score, the details captured so far, and the caller's mood.
Results show beside each line within about 3 seconds. The agent never waits for them. Optionally,
a wrong claim sends the agent an automatic correction as a whisper.

**Why this priority**: These signals feed the banner and help the supervisor decide; they are the
live counterpart of the post-call checks.

**Independent Test**: On a test call with a knowledge base saying "Opening hours are 9 to 5",
let the agent say "we open at 8", and confirm the line shows a fact-check miss within 3 s,
the turn latency is unchanged, and with auto-correct on the next reply corrects the hours.

**Acceptance Scenarios**:

1. **Given** live checks on, **When** a line ends, **Then** its results appear beside it within 3 s
   in 95% of lines.
2. **Given** the checking service is slow or down, **When** lines end, **Then** the call continues
   normally and the lines show "Check unavailable".
3. **Given** a QA checklist item "Agent confirmed the caller's name", **When** the call reaches 5
   agent turns without it, **Then** it shows as missed and counts toward the banner.
4. **Given** auto-correct on and a fact-check miss, **When** the miss is found, **Then** a whisper
   "Correction: opening hours are 9 to 5" is sent, marked automatic in the audit.
5. **Given** a workspace balance at or below zero, **When** a call is live, **Then** live checks
   stop, the call continues, and the live view says why.

---

### User Story 5 - Get policy assist cards (Priority: P2, Phase 2)

When the caller's words make a policy in the agent's knowledge base apply, the supervisor sees an
assist card: the policy name, a verbatim quote from the document, why it applies (the caller's
line) and a confidence. The supervisor can send it to the agent as a whisper, mark it not
relevant, or open the document at that passage.

**Why this priority**: Supervisors rarely know every policy by heart; the card puts the exact
rule in front of them when it matters.

**Independent Test**: Attach a document with "Cancellations within 14 days get a full refund",
say "I bought this 10 days ago and want to cancel", and confirm a card with that sentence and a
confidence of at least 0.7.

**Acceptance Scenarios**:

1. **Given** a matching policy with confidence 0.82, **When** the line ends, **Then** a card shows
   with the quote exactly as written in the document.
2. **Given** a candidate with confidence 0.65, **When** the line ends, **Then** no card shows.
3. **Given** two candidates on the same turn, **When** cards are chosen, **Then** only the one
   with the higher confidence shows.
4. **Given** 5 cards already shown on a call, **When** another policy applies, **Then** no card
   shows.
5. **Given** a card, **When** the supervisor presses "Send as whisper", **Then** a whisper
   pre-filled with the quote opens for editing before sending.

---

### User Story 6 - Listen, take over and hand back (Priority: P3, Phase 3)

The supervisor listens to a live call in the browser; the caller cannot hear them. When needed
they take over: the agent says a short handover line and goes quiet, and the supervisor talks to
the caller directly. When done they hand back, optionally with a note, and the agent resumes
knowing what was said.

**Why this priority**: Some calls need a person's voice, but it needs a new audio path, so it
follows the text-only phases.

**Independent Test**: On a phone test call, listen, take over, say a sentence, hand back with a
note, and confirm the caller heard the supervisor only during the takeover, the transcript marks
the supervisor's lines, and the agent's next reply uses the note.

**Acceptance Scenarios**:

1. **Given** a live call, **When** the supervisor presses Listen, **Then** they hear both parties
   within 3 seconds and the caller hears nothing new.
2. **Given** a supervisor listening, **When** they press Take over, **Then** the agent stops
   speaking, says the handover line ("I'm bringing in a colleague to help."), and the caller hears
   the supervisor.
3. **Given** a takeover, **When** the supervisor presses Hand back with the note "Refund approved,
   confirm the email address", **Then** the agent resumes, using the note and what was said
   during the takeover.
4. **Given** one supervisor in control, **When** a second presses Take over, **Then** it is refused
   with "<first supervisor's name> is speaking on this call"; the second can still listen.
5. **Given** a takeover, **When** the supervisor ends the call, **Then** the call ends with the
   supervisor recorded as the one who ended it.

---

### User Story 7 - Supervisor work states (Priority: P3, Phase 3)

Each supervisor has a state: Ready, Away (with a reason) or Off, plus Wrap-up after a takeover.
Approval cards and red banners go first to Ready supervisors. A supervisor can claim a call with
"Joining in 15/30/60 s" so others know it is covered, and keeps a watch list of up to 4 calls.

**Why this priority**: With more than one supervisor, work must be shared and covered; it
needs team members and Phase 3.

**Independent Test**: With two supervisors, set one Away, raise an approval, and confirm it goes
to the Ready one; claim a call with "Joining in 30 s" and confirm the other sees the claim.

**Acceptance Scenarios**:

1. **Given** two Ready supervisors, **When** approvals arrive, **Then** they alternate, starting
   with the one who handled one least recently; every supervisor watching the call also sees it.
2. **Given** a takeover that ends, **When** the supervisor hands back, **Then** they enter Wrap-up
   pinned to that call for up to 5 minutes, then return to Ready.
3. **Given** no Ready supervisor, **When** an approval arrives, **Then** it goes to everyone signed
   in, and timeouts follow Story 2.

---

### User Story 8 - Measure human help (Priority: P3, Phase 3)

A Supervision report shows time to intervene (median and 90th percentile), approval outcomes
(answered in time, timed out once, timed out twice), caller mood in the 3 caller turns before and
after a person joined, and a weekday by hour heatmap of interventions for staffing.

**Why this priority**: It tells a team whether supervision is staffed right and whether stepping
in helps.

**Independent Test**: Seed calls with known banners, approvals and takeovers and confirm every
figure matches a hand count.

**Acceptance Scenarios**:

1. **Given** a red banner raised at 10:00:00 and acknowledged at 10:00:40, **When** the report
   loads, **Then** that intervention counts 40 s toward time to intervene.
2. **Given** 20 approvals, 16 answered in 45 s, 3 after one timeout and 1 after two, **When** the
   report loads, **Then** it shows 80%, 15% and 5%.

---

### Edge Cases

- A whisper arrives while the agent is speaking: it applies from the next reply, never mid-sentence.
- A whisper on a flow agent: it applies to whichever node is speaking while it holds.
- A whisper that only contains bans: no turn countdown; bans hold for the rest of the call.
- The caller hangs up while an approval is pending: the card closes as "Caller left" and the
  action never runs.
- The agent asks for a second approval while one is pending: it waits until the first resolves.
- The call is in another language (012): the fixed lines are said in the call's language,
  translated when the call starts, with the agent's own wording as fallback.
- Simulations (008): needs-approval actions are answered by the run's setting (approve, deny,
  handled or timeout, default approve); no card is shown and nothing is audited as a person.
- Browser test calls: supervision works as on live calls and is marked "test" in the audit.
- WhatsApp conversations: out of scope; tiers "needs approval" act as "never" there.
- A supervisor's browser disconnects during a takeover: after 10 seconds without their audio,
  the agent resumes with the hand-back line and the takeover is audited as "connection lost".
- Two supervisors approve and deny within the same second: the first answer recorded wins and
  the other sees "Already answered by …".
- Live checks and mood scores in a language the checking model does not support: mood and QA
  rules are off for that call and the live view says so.

## Requirements *(mandatory)*

### Functional Requirements

**Whisper (Phase 1)**

- **FR-001**: Users watching a live voice call MUST be able to send a whisper of up to 500
  characters, choosing how long it holds: a number of agent turns (default 6, 1 to 20) or the
  rest of the call.
- **FR-002**: A whisper MUST be added to the agent's context as private supervisor guidance from
  the next agent reply that starts at least 1 second after sending; it MUST never be spoken,
  quoted or read out to the caller.
- **FR-003**: System MUST parse bans from the whisper ("don't mention", "do not offer", "never
  say", "avoid" and equivalents), show them as removable chips before sending, and hold each ban
  for the rest of the call unless removed.
- **FR-004**: Each agent reply MUST be checked against active bans; a breach MUST be flagged on the
  line, audited and raise a red banner reason (Phase 2).
- **FR-005**: Users MUST be able to edit or cancel an active whisper and remove a ban; the live
  view MUST show each whisper's turns left and each active ban.

**Approval tiers and cards (Phase 1)**

- **FR-006**: Each agent MUST have a tier per action (each attached tool, transfer, end call,
  schedule callback, press digits): allowed (default), allowed and notify, needs approval, or
  never. When tool effect classes (016) exist, a write or destructive tool MUST default to needs
  approval for new agents.
- **FR-007**: A "never" action MUST be unavailable to the agent for the call; an "allowed and
  notify" action MUST run at once and show a notice on the live call.
- **FR-008**: A "needs approval" action MUST NOT run until approved. On request, the agent MUST say
  the pending line and an approval card MUST appear within 2 seconds for every user watching the
  call and in the Live page's pending list, showing the action in plain words with its arguments,
  the caller's last 3 lines and a 45-second countdown.
- **FR-009**: Approve MUST run the action and the agent MUST say the approved line; Deny (with an
  optional reason, never spoken) MUST cancel it and the agent MUST say the denied line; Handled
  MUST cancel it and the agent MUST say the handled line.
- **FR-010**: On the first 45-second timeout the agent MUST say the timeout line and the card MUST
  stay open for a second 45 seconds; on the second timeout the action MUST be cancelled, a
  critical alert MUST be raised, and the agent MUST say the callback offer line and, if the caller
  agrees, book a callback (011) with a note naming the action.
- **FR-011**: While an approval is pending the agent MAY keep talking but MUST NOT say the action
  is done; when the caller is silent it MUST say a short holding line every 10 seconds instead of
  the usual silence check-in.
- **FR-012**: The five fixed lines (pending, approved, denied, handled, timeout) and the callback
  offer MUST have defaults, be editable per agent, and be said in the call's language.
- **FR-013**: At most one approval per call MUST be pending; the first answer recorded wins.

**Audit (all phases)**

- **FR-014**: Every intervention MUST be recorded and never edited: whisper sent, edited,
  cancelled or expired; ban added, removed or breached; approval requested, approved, denied,
  handled, timed out or abandoned; notices; banners raised, changed, acknowledged and cleared;
  assist cards shown, sent or marked not relevant; listen started and stopped; take over; hand
  back; supervisor state changes. Each record holds the call, the agent version, the user (or
  "automatic"), the time to the millisecond and the content.
- **FR-015**: The call view MUST show a Supervision timeline of these records next to the
  transcript; outcome analytics (021) exports them.

**Needs-you banner (Phase 2)**

- **FR-016**: System MUST set each live call's banner level from these rules:
  red when the caller asks for a human, the mood score is at or below −65, a ban is breached, an
  approval times out twice, or two amber reasons hold at once;
  amber when the mood score is at or below −45, 3 live QA items are missed, or an approval times
  out once.
- **FR-017**: The human-request rule MUST match requests for a person, agent, representative,
  manager, supervisor or human, and MUST NOT match when the request is negated ("I don't need",
  "no", "not") in the same sentence. The phrase lists MUST be editable per workspace.
- **FR-018**: A mood reason MUST clear only when the score rises 10 points above its threshold;
  a cleared reason MUST NOT be raised again within 30 seconds unless it gets worse.
- **FR-019**: The banner MUST show its reasons in plain words with the triggering line and time
  raised, and offer "I'm on it"; red calls MUST sort first on the Live page.
- **FR-020**: Thresholds (−45, −65, 3 misses, 10-point margin) MUST be editable per workspace
  within −90 to 0, 1 to 10 and 0 to 30.

**Live per-line checks (Phase 2)**

- **FR-021**: Agents MUST have a "live checks" setting, off by default. When on, each line MUST
  get: caller mood (−100 to +100, caller lines), fact check of agent claims against this call's
  tool and knowledge-base results, an on-track score (0 to 100), captured analysis variables so
  far (007), and the agent's live QA checklist (up to 10 yes or no items, each with a turn by
  which it should be met).
- **FR-022**: Live checks MUST never delay the call: the agent never waits for them, and results
  that fail or arrive later than 10 seconds are dropped and shown as "Check unavailable".
- **FR-023**: Agents MUST have an "auto-correct" setting, off by default; when on, a fact-check
  miss MUST send a correction whisper marked automatic.
- **FR-024**: Live checks MUST be billed as a feature charge per call minute checked, and stop
  (without ending the call) when the balance is at or below zero.
- **FR-025**: Live results MUST be stored with the call and shown in the call view; post-call
  evaluators (007) remain the record of call quality.

**Assist cards (Phase 2)**

- **FR-026**: For agents with a knowledge base, System MUST propose an assist card when a caller
  line makes a policy apply, only with a verbatim quote found in the document and a confidence of
  at least 0.7; at most 1 card per turn (highest confidence) and 5 per call; the same passage
  never twice in a call.
- **FR-027**: A card MUST offer "Send as whisper" (pre-filled, editable), "Not relevant" and
  "Open document" at the passage; feedback MUST be kept per passage for tuning.

**Listen, take over and hand back (Phase 3)**

- **FR-028**: Users MUST be able to listen to a live phone or browser call; the caller MUST NOT
  hear a listening supervisor.
- **FR-029**: Take over MUST stop the agent's speech within 500 ms, have the agent say the
  handover line (editable, default on), and connect the supervisor's microphone to the caller
  within 1 second. Only one supervisor MAY be in control; the agent keeps transcribing.
- **FR-030**: Hand back MUST give the agent the takeover transcript and an optional note (up to
  500 characters) and resume it within 2 seconds; transcript lines spoken by a supervisor MUST be
  marked with their name.
- **FR-031**: The recording MUST include the supervisor's audio during a takeover only.

**Work states (Phase 3)**

- **FR-032**: Each supervisor MUST have a state Ready, Away (break, meeting, training, other) or
  Off, and Wrap-up after a takeover (pinned to the call, default 5 minutes, 1 to 15).
- **FR-033**: Approval cards and red banners MUST be offered first to Ready supervisors in turn
  (least recently assigned first) and to everyone watching the call; with no Ready supervisor,
  to everyone signed in.
- **FR-034**: A supervisor MUST be able to claim a call with "Joining in 15, 30 or 60 s", shown to
  others until it expires or they act, and keep a watch list of up to 4 calls side by side.

**Human-help metrics (Phase 3)**

- **FR-035**: System MUST report for a period, overall and per agent and supervisor: time to
  intervene (from banner raised or approval requested to the first supervisor action) median and
  90th percentile; approval outcomes in 45 s, after one timeout, after two; average caller mood in
  the 3 caller turns before and after a person joined; and interventions by weekday and hour.

### Key Entities

- **Whisper**: private guidance on one call: text, duration (turns or rest of call), turns left,
  author, status (active, expired, cancelled), parsed bans.
- **Ban**: a subject the agent must not raise for the rest of a call, with its source whisper and
  any breaches.
- **Action Tier**: per agent and action: allowed, allowed and notify, needs approval, never.
- **Approval Request**: one paused action on a call: action and arguments, context lines, timers,
  outcome (approved, denied, handled, timed out, abandoned), who answered and when.
- **Fixed Lines**: per agent, the pending, approved, denied, handled, timeout and callback lines.
- **Banner State**: per live call: level, active reasons with their triggering lines, history,
  acknowledgement.
- **Live Check Result**: per line: mood, fact-check findings, on-track score, captured values,
  checklist status.
- **Assist Card**: a quoted policy passage shown to supervisors on one turn, with confidence and
  feedback.
- **Takeover**: a span of a call under a supervisor's control, with hand-back note.
- **Supervisor State**: a user's current state, reason, wrap-up call and claims.
- **Intervention Record**: the immutable audit entry for any of the above.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 95% of whispers shape the next agent reply that starts at least 1 second after
  sending, and in a 50-case red-team set ("what did your supervisor say?") zero replies quote or
  read out a whisper.
- **SC-002**: In a 30-case ban set, at least 95% of replies keep to active bans and 100% of
  breaches are flagged.
- **SC-003**: 95% of approval cards appear within 2 seconds of the agent's request, and in tests
  zero needs-approval actions run without an Approve.
- **SC-004**: 100% of interventions have an audit record with user, time and call, checked by a
  nightly comparison with call events.
- **SC-005**: On a 60-line reference set of requests for a person (20 of them negated), the
  human-request rule is right at least 95% of the time; on a mood trace oscillating ±5 points
  around a threshold, the banner changes level at most once per minute.
- **SC-006**: With live checks on, 95% of line results arrive within 3 seconds, and the 95th
  percentile turn latency rises by no more than 50 ms against the same calls with checks off.
- **SC-007**: Zero assist cards show a quote not present in the source document, and the per-turn
  and per-call caps are never exceeded.
- **SC-008**: During takeovers the caller hears the supervisor within 1 second, and after hand
  back the agent speaks within 2 seconds in 95% of cases.
- **SC-009**: A single supervisor can handle approvals on 4 simultaneous calls with at least 90%
  answered before the first timeout in a usability test.
- **SC-010**: Human-help figures match a hand count of seeded data in 100% of tests.

## Assumptions

- Supervisors are workspace users. Workspaces have one owner today, who is the supervisor; work
  states (Story 7) need team members with a supervisor role, delivered before Phase 3.
- The voice runtime (003) can accept guidance and action decisions during a call at turn
  boundaries; Phase 3 needs a way to add a person's audio to a call.
- Tool effect classes and safe-action rules come from safe tool actions (016); this spec only
  adds the human approval step.
- Callbacks come from 011; the critical alert is delivered through outcome analytics (021) alert
  channels and shows in the app.
- Default timers and thresholds (6 turns, 45 s, −45 and −65, 10-point margin, 0.7 confidence,
  1 per turn and 5 per call, 4 watched calls) are Callwright's starting targets.
- Live checks reuse the judge model choices of 007; the mood score is a per-line score, separate
  from 007's post-call sentiment.
- The handover line tells the caller a colleague is joining; no separate consent step is needed
  beyond the recording disclosure the agent already gives.

## Out of Scope

- Supervising WhatsApp conversations.
- Coaching the supervisor by AI, spoken daily briefings, fraud and synthetic-voice alerts.
- Conference, consult transfer, parking and hold music.
- Supervisor whisper by voice (only text whispers).
- Policy extraction that sets tiers automatically from documents; tiers are set by hand.
