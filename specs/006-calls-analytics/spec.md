# Feature Specification: Calls and Analytics

**Feature Branch**: `006-calls-analytics`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Call history with every column, sorting, filters, pagination and multi-select to start a simulation; a call detail view with transcript (including tool calls), recording playback, summary, sentiment, analysis variables, per-turn latency, flow transitions and an itemised cost with surcharge lines; a page that compares two calls side by side; a dashboard with period presets, custom range, agent filter, KPI totals, calls per day, talk time, disconnect reasons, sentiment, channels, agent leaderboard and distribution, per-evaluator pass rate and agent health against the prior 30 days; an 'ask about your data' assistant that answers questions with text plus an optional chart or table, reading only the workspace's own data through a safe read-only query layer and billed as a feature charge; and a push-to-talk voice copilot that turns speech into navigation, copilot hand-offs, UI actions, short answers or a polite decline."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find any call in the history (Priority: P1)

An operator opens Call History and sees every call in their workspace, newest first, 20 per page.
Each row shows: call ID, start time, agent ID, agent name, from number, to number, channel
(web, inbound phone, outbound phone, WhatsApp), disconnect reason, duration, status, cost (hover
shows the itemised breakdown), average turn latency, an inline recording player with seek and
download, a transcript button, summary, sentiment, analysis values and a quality cell (evaluator
outcome and the operator's own label). They sort by start time, duration, cost or average latency,
filter by status, channel, disconnect reason, sentiment, agent, call ID, date range, from/to
number, their own label and evaluation outcome, see active filters as removable chips with
"Clear all", and page through results. They can tick calls across pages and press "Run simulation"
to hand the selection to the simulation feature.

**Why this priority**: The call record is the raw material for every other quality feature. An
operator who cannot find and read a call cannot debug an agent.

**Independent Test**: Seed 45 calls across 2 agents, 3 channels and 4 statuses; confirm default
order, page counts (20/20/5), each filter alone and combined, sorting both ways, and that the
selection count survives paging.

**Acceptance Scenarios**:

1. **Given** 45 calls, **When** the operator opens Call History, **Then** the first 20 newest calls
   show with "1 to 20 of 45" and 3 pages.
2. **Given** the list, **When** the operator filters channel = WhatsApp and status = completed,
   **Then** only calls matching both show, two chips appear, and "Clear all" restores the full list.
3. **Given** a call with a cost, **When** the operator hovers the cost cell, **Then** a popover
   shows the per-component lines and any surcharge lines with their multiplier.
4. **Given** 3 calls ticked on page 1 and 2 on page 2, **When** the operator returns to page 1,
   **Then** the 3 remain ticked and the toolbar says "5 selected".
5. **Given** a selection spanning two agents, **When** the operator presses "Run simulation",
   **Then** the action is blocked with "Select calls from a single agent to run a simulation".
6. **Given** filters that match nothing, **When** the list loads, **Then** it shows "No calls match
   these filters" with a "Clear filters" action.
7. **Given** calls produced by simulations, **When** the operator views history without changing
   the origin filter, **Then** those calls are hidden; switching the origin filter to include
   simulated calls shows them with a "Simulated" tag.
8. **Given** the list, **When** the operator opens the rows-per-page control, **Then** it offers
   10, 20 (default), 50 and 100.
9. **Given** status, agent and own-label filters applied, **When** the list renders, **Then**
   three chips show (one per filter, the label included), the filter badge reads 3, and an own
   label of "Any" adds no chip and is not counted.
10. **Given** a call from +1 555 123 4567, **When** the operator types "+1555" or "1 (555)" in the
    From number filter, **Then** the call is found: the plus sign reaches the server intact and
    spaces, dashes and brackets are ignored.
11. **Given** the viewer's timezone is Asia/Kolkata and a call started at 2026-09-30 20:00 UTC,
    **When** the operator filters the single date 2026-10-01, **Then** the call is included,
    because dates are calendar days in the viewer's timezone and the end date is inclusive.
12. **Given** the column menu, **When** the operator hides Summary and Analysis, **Then** those
    columns disappear and stay hidden on the next visit in the same browser; call ID, start time
    and status cannot be hidden.
13. **Given** a filtered and sorted list of 120 calls, **When** the operator exports, **Then** a
    CSV with those 120 rows in the same order and the visible columns downloads.

---

### User Story 2 - Understand exactly what happened on one call (Priority: P1)

From any row the operator opens the call detail. It shows the header (agent and the agent version
the call ran, channel, numbers, start time, duration, status, disconnect reason), the recording
player, the transcript as a conversation with tool calls and tool results inline, an "Interrupted"
marker on cut-off agent turns, the caller's speech-recognition confidence per turn, a latency chip
on every agent turn (end-to-end, plus speech recognition, model first token and speech synthesis
parts), the flow path (nodes visited and the transition taken) for flow agents, the summary, the
sentiment, the analysis values as a field/value table, and the cost breakdown. A "Copy transcript"
action copies plain text including tool lines. Quality checks and the operator's review appear in
the same view when the quality feature is enabled.

**Why this priority**: Debugging a voice agent means reading and hearing one call end to end with
timing and tool context.

**Independent Test**: Open a seeded flow-agent call with 6 turns, 2 tool calls (one failed), one
interruption and a recording; confirm every element above renders with the seeded values.

**Acceptance Scenarios**:

1. **Given** a call with a recording, **When** the operator presses play, **Then** audio starts
   within 2 seconds, seeking works, and download saves a file named after the call ID.
2. **Given** a recording link that has expired while the view stayed open, **When** the operator
   presses play again, **Then** a fresh link is obtained transparently and playback continues.
3. **Given** a call whose recording was removed by the workspace retention policy, **When** the
   detail opens, **Then** the player area reads "Recording deleted under your retention policy" and
   the transcript and metadata still show.
4. **Given** a tool call that returned an error, **When** the transcript renders, **Then** the tool
   result is marked as an error and its duration shows.
5. **Given** an agent turn with no measured speech synthesis timing, **When** its latency chip
   renders, **Then** the missing part reads "n/a" and no value is invented.
6. **Given** a single-prompt agent call, **When** the detail opens, **Then** the flow path section
   is not shown.
7. **Given** a call still in post-call processing, **When** the detail opens, **Then** summary,
   sentiment and analysis show "Processing" and update without a reload when ready.
8. **Given** the cost breakdown of the reference call from the platform foundation spec, **When**
   it renders, **Then** the header reads "4:31 · 4.52m · $0.106/m avg" and the LLM token surcharge
   line shows a 1.13x multiplier.

---

### User Story 3 - See the whole fleet at a glance (Priority: P2)

The operator opens the Dashboard, picks a period (all time, last 7, 30 or 90 days, or a custom
range) and optionally one or more agents, and sees: KPI tiles for total calls (with daily
average), total talk time (with peak day), total cost (with cost per call), average duration and
median turn latency (with p95), each with a sparkline; calls per day and talk time per day; why
calls ended; average duration trend; sentiment split; channel split; a leaderboard of the 5 most
active agents with their positive and negative sentiment counts; a distribution of calls across
the top 10 agents with the rest grouped as "Others"; a per-evaluator pass-rate grid for the period
with the change against the previous period of equal length; and "Agent health": the headline
evaluators' pass rate for the last 30 days against the 30 days before, in percentage points.

**Why this priority**: The dashboard answers "is anything wrong" quickly, but operators can work
from the call list alone at first.

**Independent Test**: Seed calls on known days for 3 agents with known durations, costs,
sentiments, channels, disconnect reasons and evaluator verdicts; confirm every number and series
for "last 7 days" and for one agent.

**Acceptance Scenarios**:

1. **Given** 10 calls in the last 7 days and 5 older, **When** "7d" is selected, **Then** total
   calls is 10, the daily series has 7 points including zero days, and the daily average is 1.43.
2. **Given** a custom range whose end is before its start, **When** the operator applies it,
   **Then** the range is rejected with "End date must be on or after start date".
3. **Given** 12 agents with calls, **When** the distribution renders, **Then** it shows 10 named
   slices plus "Others" with the remaining count.
4. **Given** a headline evaluator with a 90% pass rate in the last 30 days and 80% in the prior 30,
   **When** Agent health renders, **Then** it shows 90% and "+10 pp".
5. **Given** no evaluator runs in the period, **When** the quality section renders, **Then** it
   reads "No evaluator runs in this period. Turn on quality checks for an agent to see pass rates."
6. **Given** the operator's browser timezone is Asia/Kolkata, **When** a call starts at 23:30 UTC,
   **Then** it is counted on the next calendar day in the daily series.
7. **Given** the dashboard on "Last 30 days", **When** the operator picks "7d" or another agent,
   **Then** every section reloads for the new selection without a separate apply step, and the
   active selection shows as chips with "Clear all" returning to the defaults.
8. **Given** a loaded dashboard, **When** the operator presses Refresh, **Then** every section
   (KPIs, charts, quality and agent health) reloads and the "Updated" time changes.

---

### User Story 4 - Compare two calls side by side (Priority: P2)

From a call, the operator opens the compare page against another call (typically the output of a
simulation of the original). It shows both headers (agent version, duration, cost, status), both
transcripts side by side aligned by turn, the flow path of each, per-turn latency of each, and,
when the quality feature is enabled, a verdict-difference table (evaluator, original verdict and
score, other verdict and score, score change, rationale on the other call).

**Why this priority**: Comparison is how operators judge whether a change helped; it becomes
essential once simulations exist.

**Independent Test**: Open the compare page for two seeded calls of the same agent with different
transcripts and flow paths; confirm alignment and that differing flow nodes are highlighted.

**Acceptance Scenarios**:

1. **Given** two calls in the same workspace, **When** the compare page opens with both, **Then**
   both transcripts render side by side and turn N of one lines up with turn N of the other.
2. **Given** a call ID from another workspace, **When** the compare page is requested, **Then** it
   responds "Call not found" and reveals nothing about the other call.
3. **Given** a simulation run reference instead of a second call ID, **When** the page opens,
   **Then** it resolves the run to its output call and labels the right side "Simulated".

---

### User Story 5 - Ask a question about my data (Priority: P3)

From a floating "Ask about your data" panel (expandable to a wide split view, with "New chat"), the
operator types a question such as "Total calls this month", "Cost by agent", "Busiest day last
week" or "Average call duration trend". The assistant replies with a short text answer and, when
useful, a chart (bar, line, area or pie) or a table. A "How this was computed" disclosure lists
the metrics, groupings, filters and period used. Follow-up questions use the earlier conversation.
Questions about specific calls ("What did my last call cost?", "Show my last 5 calls", "the most
expensive call this month", a call by ID) answer with each call's cost, duration, agent, status and
latency and a link that opens the call; they include test calls. Totals count live calls unless
the operator asks to include test calls, and say so when test calls were left out. A question the
assistant cannot answer gets what it can answer instead and two or three example questions.
Each answered question is charged to the workspace as an analytics feature charge and appears in
usage reporting.

**Why this priority**: High delight, but every answer is also available on the dashboard or the
call list.

**Independent Test**: Seed known data; ask "How many calls did each agent take last week?" and
confirm the table matches a direct count, a feature charge is recorded once, and asking about
another workspace's agent returns nothing from that workspace.

**Acceptance Scenarios**:

1. **Given** seeded calls, **When** the operator asks "Cost by agent this month", **Then** the
   answer includes a bar chart whose values equal the per-agent cost totals for the month.
2. **Given** a question the data cannot answer (for example "What is our churn rate?"), **When** it
   is asked, **Then** the assistant says what it can answer instead and no data query runs.
3. **Given** a question that tries to reach other workspaces or alter data (for example "delete all
   calls" or "show calls for workspace X"), **When** it is asked, **Then** nothing is changed, no
   other workspace's data is read, and the assistant declines.
4. **Given** a balance at or below zero, **When** the operator asks a question, **Then** it is
   refused with an "add funds" message and nothing is charged.
5. **Given** the same request retried after a network error with the same request key, **When** it
   arrives twice, **Then** the workspace is charged once.
6. **Given** a question that fails, **When** the error shows, **Then** it names the cause and the
   next step (add funds when out of credit, retry when the service timed out or is unavailable,
   example questions when the data cannot answer it) and the typed question stays in the input.

---

### User Story 6 - Drive the app by voice (Priority: P3)

Anywhere in the app (except while typing in a text field) the operator holds the Space key, or
presses the mic button and presses it again to send, and speaks, for
example "show me failed calls from yesterday", "open the analytics assistant and ask what our
busiest day was", "save the flow", or "what page am I on". On release the speech is transcribed
and interpreted into one of five outcomes: navigate (go to a page, optionally with filters applied),
hand off to a copilot (analytics assistant, prompt builder or flow builder) with the question
prefilled, perform a UI action the current page has registered, give a short spoken-style text
answer, or decline with a suggestion and a highlight of the relevant control. State feedback
covers listening, microphone blocked, offline, "Didn't catch that", and a "Try typing instead"
hint after repeated failures.

**Why this priority**: Convenience feature; every outcome is reachable by mouse and keyboard.

**Independent Test**: With a test transcript "show me failed calls from yesterday" on the
dashboard, confirm navigation to Call History with status = failed and yesterday's date range
applied.

**Acceptance Scenarios**:

1. **Given** the dashboard, **When** the operator says "show failed calls from yesterday", **Then**
   Call History opens with those two filters as chips.
2. **Given** the flow builder with unsaved changes, **When** the operator says "save the flow",
   **Then** the page's registered save action runs exactly as if the button were pressed.
3. **Given** a command for an action the current page has not registered (for example "delete this
   agent" on the dashboard), **When** it is interpreted, **Then** the result is a decline with a
   suggestion, and nothing happens.
4. **Given** the microphone permission is denied, **When** the operator holds Space, **Then**
   "Microphone blocked" shows with how to allow it, and the typing fallback is offered.
5. **Given** focus is in a text field, **When** the operator presses Space, **Then** a space is
   typed and push-to-talk does not start.
6. **Given** the live transcription link cannot be obtained, **When** the operator speaks, **Then**
   the clip is recorded and transcribed after release instead, with the same outcome.

---

### Edge Cases

- A call is still in progress: it appears in history with status "In progress", no cost and no
  recording; duration counts up in the detail view; it is excluded from dashboard duration and
  cost until it ends.
- A call failed before connecting (no answer, busy, failed): duration 0, no transcript, no
  recording; the row still shows status and reason.
- Very long transcripts (over 500 turns): the detail view loads progressively without freezing.
- Agent deleted after its calls: rows keep the agent name captured at call time, marked "(deleted)".
- Selection for simulation larger than the simulation limit (200 calls): blocked with the limit.
- Filters in the URL that reference unknown values: the unknown values are dropped with a notice.
- Dashboard "All time" over very large histories: totals still return within the performance
  target; series switch from daily to weekly buckets when the range exceeds 180 days.
- Analytics answers that would return more than 100 rows: the table is truncated to 100 with a
  "showing first 100" note.
- The assistant's model provider is down: the question fails with a retry message and is not
  charged.
- Voice copilot in a browser without microphone support: the button is hidden and the typed input
  is offered instead.
- Two browser tabs on different pages: each tab interprets voice commands against its own page.

## Requirements *(mandatory)*

### Functional Requirements

**Call history**

- **FR-001**: System MUST list the workspace's calls newest first with pagination (page sizes 10,
  20, 50 and 100; default 20) and report total count and total pages.
- **FR-002**: System MUST show for each call: call ID, start time, agent ID, agent name at call
  time, from and to numbers, channel, disconnect reason, duration, status, cost, average turn
  latency, recording availability, summary, sentiment, analysis values, evaluation outcome and the
  viewer's own label.
- **FR-003**: Users MUST be able to sort by start time, duration, cost or average latency, ascending
  or descending.
- **FR-004**: Users MUST be able to filter by status, channel, disconnect reason, sentiment, agent
  (multi-select), call ID (exact or prefix), start date range, from number, to number, own label
  (good, bad, unannotated), evaluation outcome and origin (live, test, simulated); multi-value
  filters combine with OR inside a filter and AND across filters.
- **FR-005**: System MUST keep the current sort, filters and page in the address so a view can be
  shared and restored.
- **FR-006**: Users MUST be able to select calls across pages (up to 200), see the selection count,
  and start a simulation for a single-agent selection; mixed-agent selections MUST be blocked with
  an explanation.
- **FR-007**: System MUST hide calls produced by simulations unless the origin filter includes them.

**Call detail**

- **FR-008**: System MUST show the call header including the agent version the call ran.
- **FR-009**: System MUST render the transcript as ordered items of three kinds: spoken message
  (speaker, text, interrupted flag, recognition confidence for caller turns, offset from call
  start), tool call (tool name, arguments) and tool result (output, error flag, duration).
- **FR-010**: System MUST provide a plain-text transcript copy with tool calls and results as
  bracketed lines.
- **FR-011**: System MUST play and download the recording through a link that expires within
  10 minutes and is refreshed automatically on expiry; access MUST be denied to anyone outside the
  workspace.
- **FR-012**: System MUST show per agent turn: end-to-end latency and its speech recognition, model
  first token and speech synthesis parts as measured, never estimated; and per call: average,
  median and p95 end-to-end latency and the number of measured turns.
- **FR-013**: System MUST show the flow path for flow-agent calls: each transition with from node,
  to node and the transition taken, in order.
- **FR-014**: System MUST show summary, sentiment (positive, neutral, negative, unknown) and analysis
  values, with a processing state while post-call analysis runs.
- **FR-015**: System MUST show the itemised cost: per component (speech recognition, model, speech
  synthesis, noise cancellation when non-zero, platform) rate, billed minutes and cost; a header with
  duration, billed minutes and average rate per minute; and separate surcharge lines with their
  multiplier for components whose usage exceeded the per-minute bundle.

**Compare**

- **FR-016**: Users MUST be able to compare any two calls of their workspace, or a call and a
  simulation run's output, side by side: headers, transcripts aligned by turn, flow paths with
  differing nodes highlighted, per-turn latency, and verdict differences when quality checks exist.

**Dashboard**

- **FR-017**: System MUST offer period presets all time, last 7 days, last 30 days (default), last
  90 days and custom range, plus an agent multi-select; day boundaries use the viewer's timezone.
- **FR-018**: System MUST show KPIs for the period: total calls, daily average, total talk time,
  peak day, total cost, cost per call, average duration, median and p95 turn latency.
- **FR-019**: System MUST show daily series for calls and talk time with zero-filled days (weekly
  buckets beyond 180 days), an average duration trend, counts by disconnect reason, sentiment and
  channel, the top 5 agents by calls with positive and negative counts, and the top 10 agents by
  calls with the rest as "Others".
- **FR-020**: System MUST show per evaluator for the period: pass rate (passes divided by passes
  plus fails, not-applicable excluded), average score, pass, fail and not-applicable counts, calls
  evaluated, and the change against the previous period of equal length.
- **FR-021**: System MUST show Agent health: each headline evaluator's pass rate over the last 30
  days against the prior 30 days, with the change in percentage points, independent of the selected
  period.
- **FR-022**: Dashboard totals MUST count only ended calls of origin live (test and simulated calls
  excluded) and costs MUST equal the sum of the itemised call costs.

**Analytics assistant**

- **FR-023**: Users MUST be able to ask questions in natural language, with prior turns of the
  conversation as context, and receive a text answer plus an optional chart (bar, line, area, pie)
  or table (at most 100 rows).
- **FR-024**: The assistant MUST read data only through a fixed catalog of metrics, groupings and
  filters scoped to the asking workspace; it MUST NOT be able to change any data or read another
  workspace's data, and free-form database queries written by the model MUST never be executed.
- **FR-025**: Each answer MUST include a disclosure of the metrics, groupings, filters and period
  used.
- **FR-026**: Each answered question MUST be recorded as an analytics feature charge, exactly once
  per request key; failed or declined questions are not charged; questions are refused when the
  balance is at or below zero.
- **FR-027**: The assistant MUST NOT see transcript text or caller phone numbers in v1.

**Voice copilot**

- **FR-028**: Users MUST be able to hold Space (when focus is not in a text field) or press a mic
  control to speak a command; release ends capture.
- **FR-029**: System MUST provide live transcription through a short-lived credential (valid at most
  60 seconds, usable only for transcription) and fall back to upload-then-transcribe when live
  transcription is unavailable.
- **FR-030**: System MUST interpret the transcript, together with the current page's state and its
  registered actions and the last 12 exchanges, into exactly one of: navigate, route_to_copilot,
  ui_action, answer, decline.
- **FR-031**: Navigation targets MUST be limited to known app pages and UI actions to the actions
  the current page has registered; anything else MUST become a decline with a suggestion.
- **FR-032**: System MUST show listening, microphone blocked, offline, not understood and
  "Try typing instead" states, and offer a typed command input.
- **FR-033**: Voice copilot usage MUST be recorded per workspace as feature usage (raw cost), with
  the billable amount set by the pricing catalog (zero by default).

**Live UI walkthrough additions (2026-10-16)**

- **FR-034**: Users MUST be able to hide and show call list columns; the choice MUST persist in the
  browser; call ID, start time and status MUST always be shown.
- **FR-035**: Users MUST be able to export the current filtered and sorted call list as CSV (at
  most 10,000 rows, visible columns, no transcript text); larger results MUST be refused with the
  limit and a hint to narrow the filters.
- **FR-036**: Every applied call filter MUST appear as a removable chip, the filter count MUST equal
  the number of chips, and a filter left at "Any" MUST count as not applied.
- **FR-037**: Filter values MUST reach the server unchanged (a leading plus sign or a space never
  altered in transit). Phone number filters MUST ignore spaces, dashes and brackets, treat the
  leading plus as optional, and match numbers that start with the typed digits.
- **FR-038**: Date filters MUST be calendar dates in the viewer's timezone with an inclusive end
  date; the server MUST receive the dates and the timezone and resolve them itself.
- **FR-039**: Dashboard period and agent changes MUST reload every section without a separate
  apply step (a custom range applies once both dates are valid). Refresh MUST reload every
  section and show when the data was last updated.
- **FR-040**: The dashboard MUST show the active period and agent selection as chips with a
  "Clear all" that restores the defaults.
- **FR-041**: Analytics assistant errors MUST state the cause and the next step (add funds, retry,
  or examples of answerable questions) and MUST keep the typed question for retry.

### Key Entities

- **Call (read view)**: one conversation as shown to operators; identity, agent and agent version,
  channel, numbers, origin, status, timestamps, duration, disconnect reason, cost total, latency
  summary, summary, sentiment, analysis values, recording availability.
- **Transcript Item**: one ordered element of a call: spoken message, tool call or tool result.
- **Turn Latency**: measured timing for one agent turn and its parts.
- **Flow Transition**: one move between flow nodes during a call.
- **Cost Breakdown**: per-component lines and surcharge lines for a call (owned by the platform
  foundation feature, displayed here).
- **Recording Link**: a time-limited, workspace-bound link to a call's audio.
- **Dashboard Period**: preset or custom range, timezone, agent filter; drives every dashboard
  figure.
- **Analytics Question**: a question, the validated metric queries it produced, the answer and its
  charge; logged for audit, not shown as a history in v1.
- **Voice Command**: a transcript, the page state it was spoken on, and the interpreted outcome.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Call History first page loads in under 1.5 seconds at p95 for a workspace with 1
  million calls, with any single filter applied.
- **SC-002**: The dashboard for "last 30 days" with 100,000 calls in the period renders all
  sections in under 2 seconds at p95.
- **SC-003**: Recording playback starts within 2 seconds of pressing play for 95% of calls.
- **SC-004**: 100% of dashboard totals match an independent recount of the same seeded calls in
  automated tests.
- **SC-005**: In a red-team suite of at least 50 hostile questions, zero answers read another
  workspace's data and zero change any data.
- **SC-006**: 90% of questions from a 40-question benchmark of typical operator questions get a
  correct answer on first ask.
- **SC-007**: 85% of commands from a 60-utterance voice benchmark produce the intended outcome, and
  zero produce an action the page did not register.
- **SC-008**: An operator can go from a dashboard anomaly to the transcript of an affected call in
  under 30 seconds.

## Assumptions

- Calls, transcripts, turn timings, tool events and flow transitions are written by the voice
  runtime feature (003); costs by the platform foundation feature (001); summary, sentiment,
  analysis values, evaluator outcomes and labels by the quality feature (007). Before 007 is in
  place the quality cells and sections show their empty states.
- Simulation (008) owns starting simulations and resolving a simulation run to its output call;
  this feature only hands over the selection and opens the compare page.
- Each call carries an origin (live, test, simulated); web test calls from the agent tester are
  "test".
- The viewer's browser timezone is used for day boundaries; the workspace has no fixed timezone in v1.
- Analytics assistant conversations are kept in the browser only; "New chat" clears them.
- The analytics charge per question and the voice copilot rate come from the pricing catalog (001).
- Recording retention is a workspace setting owned by 001; this feature honours it.
- Voice commands are English only in v1.
- The analytics assistant lives only in the floating panel (with an expanded view); there is no
  separate assistant page.
- Call direction and transport are one filter (channel: web, inbound phone, outbound phone,
  WhatsApp) rather than separate type and channel filters.
- Own-label values follow 007-quality-evals (good, bad, unannotated in v1); the filter offers
  whatever values 007 defines.
