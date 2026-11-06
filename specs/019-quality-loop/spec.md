# Feature Specification: Quality loop upgrades (019)

**Feature Branch**: `019-quality-loop`
**Created**: 2026-11-05
**Status**: Draft
**Input**: Close the issue loop with challenge and regression sets that run on every new version
and reopen an issue when it comes back; add audio-quality checks next to the transcript checks;
replace thumbs-only labelling with a graded rubric, plus second-pass and blind review; probe how
long an agent remembers on long calls; show how far to trust a fix and why it needs a human; keep
a library of reusable simulated callers; turn builder findings and knowledge-base policy into
fixes and checks; let a person override an evaluator's result.

## Why

The quality loop (007, 008, 009) finds recurring failures, drafts a fix, validates it and applies
it as a new version. After that the loop goes quiet:

- An applied issue only follows the headline pass rate on real calls (009 FR-024). Nothing ties
  the issue's failing calls to a dataset (008 datasets are hand-built), so a later version can
  bring the failure back unnoticed until detection runs again and opens a new linked issue
  (009 FR-004). `applied` is a final status today.
- Only one check listens to the recording: `audio_silence` reads levels from the recording to
  find long silences (007 FR-040). Noise, clipping, loudness and how natural the voice sounds are
  not measured, although 007 already reserves an `audio_quality` output kind (FR-033).
- Human labels are a thumbs up or down plus a note, one per user per call (007 FR-021). They
  say whether a call was good, not which part failed. The review queue has a disagreement
  strategy (007 FR-023) but no second opinion and no blind review.
- A person can override a test result (008 FR-009) but not an evaluator's verdict on a call;
  per-agent "overrides" today are evaluator settings, not results.
- Persona briefs are written per simulation run (008 FR-017) and are lost for reuse.
- Agent configuration checks block invalid saves and publishes, but nothing suggests
  improvements with a ready patch, and 009 leaves static findings out of scope.
- 009's keep rule says pass or fail; it does not say how confident the result is, which changes
  are too risky to apply without a careful look, or why.
- Simulations stop at 20 caller turns by default (50 at most); nobody measures when an agent
  starts forgetting what the caller said earlier.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fixed issues stay fixed (Priority: P1)

When an operator applies a fix (009), the issue's smallest set of failing calls becomes its
challenge set and joins the agent's regression set. Every new version of the agent runs the
regression set as a simulation batch. If an applied issue's challenge calls fail again, the issue
reopens, marked "Regressed in version N", with a link to the run.

**Why this priority**: A fix that silently breaks again costs more than the original failure,
because the team believes it is solved. This turns each applied issue into a lasting test.

**Independent Test**: Apply a fix for an issue with 6 sample calls, confirm the challenge set
(at most 10 calls) joins the regression set, publish a version that reverts the fix, and confirm
the regression run fails and the issue reopens with the version and run linked.

**Acceptance Scenarios**:

1. **Given** a validated issue with 14 sample calls in 3 failure clusters, **When** the operator
   opens Apply, **Then** a proposed challenge set of at most 10 calls is shown, covering every
   cluster and preferring the shortest failing calls, and the operator can remove or add sample
   calls before applying.
2. **Given** an applied issue, **When** apply finishes, **Then** its challenge calls appear in the
   agent's regression set, labelled with the issue title, and a regression run starts on the new
   version.
3. **Given** an agent with a regression set, **When** any new version is created (publish,
   create version only, apply or restore), **Then** a regression run starts on it, and only the
   newest version runs if several are created within 2 minutes.
4. **Given** an applied issue whose challenge calls passed the headline evaluator at 80% in the
   validation, **When** a new version scores 60% on them, **Then** the failing challenge calls run
   once more, and if the rate is still more than 10 points below 80%, the issue reopens as
   "Regressed in version N".
5. **Given** a new version that scores 75% on the same challenge calls, **When** the run ends,
   **Then** the issue stays applied and the run shows "Within tolerance (−5 pp)".
6. **Given** a workspace balance at or below zero, **When** a version is created, **Then** the
   regression run is skipped with "Not checked: insufficient credit" on the version and the
   operator can run it later from the regression set page.
7. **Given** the regression set page, **When** the operator presses "Run now" and picks the saved
   draft, **Then** the set runs against the draft and no issue reopens from a draft run.

---

### User Story 2 - Score calls with a graded rubric (Priority: P1)

A reviewer scores a call against the workspace rubric: each category 0 (not met), 1 (partly met),
2 (met) or not applicable, with an optional note per category, plus an overall verdict:
acceptable or not acceptable. The thumbs up or down stays as a quick label; a rubric review also
sets the reviewer's label (acceptable is good, not acceptable is bad) so calibration (007) keeps
working.

**Why this priority**: Category scores say what to fix. They make human review useful for issue
triage and calibration, not only a pass or fail.

**Independent Test**: Use the default rubric, score a call 2/2/1/0/2 with "not acceptable", and
confirm the call shows the scores, a total of 7 of 10, the label "bad" and the review in the
calibration counts.

**Acceptance Scenarios**:

1. **Given** a new workspace, **When** the reviewer opens Review on a call, **Then** the default
   rubric shows five categories: Opening and disclosure, Understanding the caller, Accuracy,
   Resolution, Tone and courtesy, each with a short description of 0, 1 and 2.
2. **Given** a category marked critical scored 0, **When** the reviewer picks "acceptable",
   **Then** the form asks for a note explaining why before it can be saved.
3. **Given** a reviewer who already reviewed the call, **When** they open Review again, **Then**
   their review opens for editing; one review per reviewer per call.
4. **Given** the rubric editor, **When** an operator adds a category, **Then** the rubric gets a
   new version and earlier reviews keep the version they were made with.
5. **Given** the call list, **When** the operator filters by "acceptable", "not acceptable" or
   "category scored 0", **Then** only matching calls show.

---

### User Story 3 - Second pass and blind review for extreme or disputed scores (Priority: P2)

Reviews that are extreme or disputed go to a second-pass queue. The second reviewer sees the call
but not the first review, the first reviewer's name or the evaluator verdicts until they submit.
If the two reviews disagree, the call goes to adjudication, where a third person sees both and
sets the final review.

**Why this priority**: One person's score on an unusual call is the least reliable input to
calibration and issue triage; a blind second look catches it.

**Independent Test**: Submit a review with a critical category at 0, confirm it enters the
second-pass queue, review it blind as a second user with "acceptable", and confirm it lands in
adjudication with both reviews side by side.

**Acceptance Scenarios**:

1. **Given** a review with total at or below 25% of the maximum, or a critical category at 0,
   **When** it is saved, **Then** the call enters the second-pass queue as "extreme".
2. **Given** a review whose overall verdict disagrees with the call's headline evaluator results
   or with another reviewer, **When** it is saved, **Then** the call enters the queue as "disputed".
3. **Given** 10% of all other reviews chosen at random, **When** they are saved, **Then** they
   enter the queue as "spot check".
4. **Given** a call in the second-pass queue, **When** a second reviewer opens it, **Then** the
   first review, its author and evaluator verdicts are hidden until the second review is saved.
5. **Given** two reviews that differ on the overall verdict or by 2 points on any category,
   **When** the second is saved, **Then** the call moves to adjudication; otherwise the two
   reviews resolve as agreed.
6. **Given** a workspace with a single member, **When** a call enters the queue, **Then** the
   second pass is offered to the same person after 24 hours with their first review hidden, and
   is marked "same reviewer".

---

### User Story 4 - Hear audio problems, not only read them (Priority: P2)

Four new built-in checks read the call recording: background noise (signal-to-noise ratio),
clipping, loudness, and a naturalness score for the agent's voice. They sit next to the transcript
checks in the evaluator catalog, with the same verdict, score, rationale and version.

**Why this priority**: Callers judge a voice agent by how it sounds. A distorted or too-quiet
voice fails the call even when every word is right.

**Independent Test**: Seed four recordings (clean, noisy caller, clipped agent audio, quiet agent
audio), turn on the four checks, and confirm each verdict and rationale.

**Acceptance Scenarios**:

1. **Given** a recording with the agent's audio clipped in 3% of frames, **When** the clipping
   check runs, **Then** it fails with the share of clipped frames and the three worst moments.
2. **Given** agent audio averaging −28 LUFS with a target of −16 ± 3, **When** the loudness check
   runs, **Then** it fails and names the measured level and the target.
3. **Given** a noisy caller and clean agent audio, **When** the noise check runs, **Then** it
   passes on the agent side and reports the caller's noise level as context.
4. **Given** a call without a recording, or a simulated call, **When** the checks run, **Then**
   they report not applicable.
5. **Given** a mono recording, **When** the checks run, **Then** they measure the mixed audio and
   say so in the rationale.

---

### User Story 5 - Keep a library of simulated callers (Priority: P2)

Operators keep reusable caller personas: a name, a prompt (goal, temperament, how they speak,
constraints), facts the caller knows and reveals when asked, and a voice. They create personas by
hand, from a simulation's extracted brief ("Save as persona"), in bulk from a file, or by copying
one. They launch one or many personas against an agent for tests and demos.

**Why this priority**: Good personas take effort to write; teams reuse the same callers across
agents and versions.

**Independent Test**: Save a run's brief as a persona, copy it, change one fact, launch both
against an agent as one batch, and confirm two standalone persona runs with the stored briefs.

**Acceptance Scenarios**:

1. **Given** a finished persona run, **When** the operator chooses "Save as persona", **Then** a
   persona is created from the run's brief with an editable name.
2. **Given** a file of 30 personas where 2 lack a goal, **When** it is imported, **Then** 28 are
   created and the 2 are listed with the missing field.
3. **Given** 5 selected personas and one agent, **When** the operator launches them, **Then** a
   batch of 5 standalone persona runs starts after the pre-flight step (008 FR-015).
4. **Given** a persona with a voice, **When** the operator presses Play, **Then** they hear the
   persona's opening line in that voice.
5. **Given** a persona used by earlier runs, **When** it is edited, **Then** earlier runs keep the
   brief they ran with.

---

### User Story 6 - Override an evaluator's result (Priority: P2)

A reviewer who disagrees with a verdict on a call overrides it (pass to fail or fail to pass)
with a reason. The original verdict stays visible. Pass rates, issue detection and review queues
use the overridden verdict, and calibration counts the override as ground truth for that
evaluator.

**Why this priority**: A known-wrong verdict otherwise keeps polluting dashboards and issues; it
is a small change with immediate effect.

**Independent Test**: Override a failing `intent_fulfillment` verdict to pass with a reason, and
confirm the call view, the dashboard pass rate and the calibration "over-eager" count change.

**Acceptance Scenarios**:

1. **Given** a failed verdict, **When** the reviewer overrides it to pass without a reason,
   **Then** saving is refused with "Add a reason".
2. **Given** an overridden verdict, **When** the call view loads, **Then** it shows the new
   verdict, the original verdict, the reason, author and time.
3. **Given** an overridden run, **When** the evaluator is re-run on the call, **Then** the new run
   has no override and shows "Previous run was overridden".
4. **Given** an override, **When** the reviewer removes it, **Then** the original verdict applies
   again and the removal is kept in the history.

---

### User Story 7 - Know when a long call starts forgetting (Priority: P3)

An operator runs a memory probe: a simulated caller gives facts early in the call (a name, a
reference number, a date, a preference and a reason for calling), keeps the conversation going,
and asks for each fact back at set turns. The report shows the turn where recall first breaks and
which fact was lost.

**Why this priority**: Long calls are where agents fail quietly; the turn where recall breaks is
a number teams can track across versions.

**Independent Test**: Run a probe with checkpoints at turns 10, 20, 30 and 40 on an agent, and
confirm the report lists each fact at each checkpoint and states "Recall holds through turn N;
first break at turn M".

**Acceptance Scenarios**:

1. **Given** default settings, **When** a probe starts, **Then** it plants 5 facts within the
   first 3 caller turns and asks for them at turns 10, 20, 30 and 40, 3 repetitions each.
2. **Given** a reference number "48213", **When** the agent answers "48231" at turn 30, **Then**
   that checkpoint fails for that fact; numbers must match digit for digit.
3. **Given** three repetitions breaking at turns 20, 30 and 30, **When** the report renders, **Then**
   it shows a median break at turn 30 and a worst case at turn 20.
4. **Given** two versions with probe results, **When** the operator compares them, **Then** the
   report shows both break turns side by side.

---

### User Story 8 - Know how far to trust a fix, and why it needs a human (Priority: P3)

Every validated fix shows a confidence (high, medium or low) with its reasons, and a list of
safety caps. A fix that trips any cap is marked "Needs a human", with each reason in plain words.
An agent can opt in to auto-apply: a high-confidence fix that trips no cap is applied without a
click, published only after its regression run passes.

**Why this priority**: Teams want to move faster on safe fixes and be stopped on risky ones;
this depends on Story 1's regression set.

**Independent Test**: Validate one small prompt fix with a large margin and one fix that edits a
transition, and confirm the first shows "High" and no caps, the second "Needs a human: changes
the call flow".

**Acceptance Scenarios**:

1. **Given** a passing validation with 12 affected calls, a 24-point improvement, no evaluator
   down more than 2 points and strong calibration, **When** the fix shows, **Then** confidence is
   high.
2. **Given** a fix that removes 40% of the prompt, **When** the fix shows, **Then** it reads "Needs
   a human: removes 40% of the prompt (cap 30%)".
3. **Given** auto-apply on and a high-confidence fix with no cap tripped, **When** validation
   passes, **Then** a version is created, the regression set runs, and the version is published
   only if the run passes; the owner is told either way.
4. **Given** auto-apply on and an auto-applied fix in the last 7 days, **When** another fix
   qualifies, **Then** it waits for a person with "Needs a human: one automatic fix per week".

---

### User Story 9 - Builder findings with patch previews; policy turned into checks (Priority: P3)

In the agent editor, a Findings panel lists problems in the configuration with a severity, where
they are, why they matter and a proposed change shown as a before-and-after preview. "Apply patch"
changes the draft; "Dismiss" asks for a reason. From a knowledge-base document attached to the
agent, the system proposes quality checks from the policies it states, each quoting the passage
it came from; accepting one creates a custom check (007).

**Why this priority**: It catches problems before any call is made, and turns written policy into
measurable checks without hand-writing judge questions.

**Independent Test**: Load a configuration whose prompt names a tool that is not attached, apply
the proposed patch, and confirm the draft changed and the finding cleared; then propose checks
from a refund policy document and accept one.

**Acceptance Scenarios**:

1. **Given** a prompt that tells the agent to use `lookup_order` when no such tool is attached,
   **When** the draft is saved, **Then** a warning finding points to the sentence and offers two
   patches: attach the tool or remove the sentence.
2. **Given** a finding, **When** the operator applies its patch, **Then** only the draft changes,
   nothing is published, and the finding disappears on the next check.
3. **Given** a document saying "Refunds above $200 need a manager's approval", **When** the
   operator asks for proposed checks, **Then** a proposal appears with that sentence quoted
   verbatim and a judge question such as "Did the agent promise a refund above $200 without a
   manager's approval?".
4. **Given** an accepted policy check, **When** its source document changes, **Then** the check is
   marked "Source changed" for review and keeps running.

---

### Edge Cases

- A challenge call's transcript or recording is purged by retention: the challenge keeps what it
  needs to run (the replay lines or the persona brief) from the moment it joined the set.
- The headline evaluator's version changed since validation: the first regression run on the new
  evaluator version sets a new baseline and cannot reopen the issue.
- The headline evaluator is turned off for the agent: the issue's challenge calls show "Can't
  check" and never reopen it.
- The regression set is full (100 calls): new challenge calls wait as "Pending, set full" until
  the operator retires calls; apply is not blocked.
- A reopened issue that 009 detection would also match on real calls: detection updates the
  reopened issue instead of creating a recurrence.
- A rubric is edited while a review is open: the review saves against the version it opened with.
- The second-pass reviewer is the call's first reviewer while another member may review it: refused.
- Audio checks on calls longer than 60 minutes: measured on the whole call; the rationale lists
  at most the 5 worst moments.
- An override on a simulated call: allowed, but it never affects live-call figures.
- A memory probe on an agent whose turn limit or call duration ends the call before the last
  checkpoint: the report marks unreached checkpoints "not reached", not failed.
- A persona's voice is removed from the catalog: the persona keeps working in text runs and asks
  for a new voice before Play.
- Auto-apply when the published version changed since validation: refused as in 009 FR-020 and
  left for a person.

## Requirements *(mandatory)*

### Functional Requirements

**Challenge and regression sets (Story 1)**

- **FR-001**: On apply (009), System MUST form the issue's challenge set from its sample calls:
  at most 10 completed live calls that failed the headline evaluator, at least one per failure
  cluster, preferring the calls with the fewest caller turns. Operators MAY add or remove sample
  calls before applying; at least 1 is required.
- **FR-002**: Each agent MUST have one regression set holding the challenge calls of its applied
  issues (at most 100 calls), each tagged with its issue, the simulation mode used in validation
  and the headline pass rate the validation's treatment arm reached on those calls.
- **FR-003**: Each challenge MUST keep what it needs to run (replay lines or persona brief) so it
  survives transcript and recording retention.
- **FR-004**: System MUST start a regression run on every new agent version (publish, create
  version only, apply, restore) when the set is not empty and the agent's "check new versions"
  setting is on (default on). If several versions are created within 2 minutes, only the newest
  runs.
- **FR-005**: A regression run MUST be one simulation batch (008) over the set against the new
  version, billed through the simulation and evaluation charges, and skipped with a stated reason
  when the balance is at or below zero.
- **FR-006**: For each applied issue in the run, System MUST compare the headline pass rate on
  its challenge calls with its stored rate. When at least 3 calls have verdicts and the rate is
  more than the regression tolerance (default 10 points, 0 to 30) below the stored rate, System
  MUST re-run that issue's failing calls once; if the rate is still below, the issue MUST reopen.
- **FR-007**: Issue status MUST gain the move `applied` to `open` with a "regressed" marker naming
  the version and run. This amends 009 FR-019, where `applied` was final.
- **FR-008**: Operators MUST be able to run the regression set on demand against the published
  version, the saved draft or any version; draft runs never reopen issues.
- **FR-009**: The regression set page MUST list challenges by issue with their last result, and
  let operators retire a challenge (kept in history) or a whole issue's challenges.

**Graded rubric (Story 2)**

- **FR-010**: Each workspace MUST have a rubric of 3 to 10 categories, each with a name, a
  description per score (0, 1, 2), and a critical flag. The default rubric MUST have the five
  categories in Story 2, with Accuracy critical.
- **FR-011**: Editing the rubric MUST create a new version; reviews keep the version they used.
- **FR-012**: A review MUST hold a score (0, 1, 2 or not applicable) and optional note (at most
  1,000 characters) per category, an overall verdict (acceptable or not acceptable), the reviewer
  and time. One review per reviewer per call.
- **FR-013**: "Acceptable" with a critical category at 0 MUST require a note.
- **FR-014**: A review MUST set or replace the reviewer's label (007): acceptable as good, not
  acceptable as bad.
- **FR-015**: The call list MUST filter by overall verdict and by "any category scored 0"; the
  call view MUST show the total as points of the maximum, excluding not-applicable categories.

**Second pass and blind review (Story 3)**

- **FR-016**: A review MUST enter the second-pass queue when it is extreme (total at or below 25%
  of the maximum, or a critical category at 0), disputed (overall verdict differs from the
  majority of the call's headline evaluator verdicts or from another review), or picked as a
  spot check (10% of other reviews, chosen at random).
- **FR-017**: A second reviewer MUST NOT see the first review, its author or the call's evaluator
  verdicts before saving. The same person MUST NOT do both passes when another member may
  review the call (023 FR-006); when nobody else may, the second pass opens no sooner than 24
  hours later with the first review hidden and is marked "same reviewer".
- **FR-018**: Two reviews that differ on the overall verdict, or by 2 points on any category, MUST
  go to adjudication, where a reviewer who did neither pass sees both and saves the final review.
  Otherwise the pair resolves as agreed and the final review is the first one.
- **FR-019**: Calibration (007) MUST use the final review's verdict when one exists.

**Audio-quality checks (Story 4)**

- **FR-020**: System MUST add four built-in evaluators of output kind `audio_quality`, scope
  call, free, all agent types, reading the recording only:
  `audio_noise` (signal-to-noise ratio per party; fails when the agent side is below `min_snr_db`,
  default 20 dB; the caller side is reported, not judged);
  `audio_clipping` (share of agent audio frames at full scale; fails above `max_clipped_pct`,
  default 0.5%);
  `audio_loudness` (agent integrated loudness; fails outside `target_lufs` ± `tolerance_lu`,
  default −16 ± 3, or when turn-to-turn swing exceeds `max_swing_lu`, default 6);
  `voice_naturalness` (estimated mean opinion score 1 to 5 for agent speech; fails below
  `min_score`, default 3.5).
- **FR-021**: Each result MUST give the measured value, the threshold, and up to 5 worst moments
  with their start times; calls without a recording and simulated calls are not applicable; mono
  recordings are measured mixed and say so.
- **FR-022**: The work to compute these checks MUST be recorded as platform usage and not charged
  to the workspace, as with `anomaly_detection` (007).
- **FR-023**: The caller-side noise level MUST be stored per call in three bands (quiet, moderate,
  noisy) for slicing (021).

**Simulated-caller library (Story 5)**

- **FR-024**: Personas MUST belong to the workspace and hold a name (unique, ignoring case), a
  prompt (goal, temperament, speaking style, constraints), facts (up to 30 name and value pairs),
  an optional voice from the voice catalog, and an optional language.
- **FR-025**: Users MUST be able to create, edit, copy, delete, import (up to 100 per file, with
  per-row errors) and export personas, and save a run's brief as a persona.
- **FR-026**: Users MUST be able to launch 1 to 50 personas against one agent; one persona runs as
  a standalone persona run and several as one batch (extending 008 FR-016), each run storing a
  copy of the persona as it was.
- **FR-027**: Play MUST speak the persona's opening line in its voice; text simulations ignore the
  voice.

**Evaluator overrides (Story 6)**

- **FR-028**: Users MUST be able to override a completed pass or fail verdict on any call with a
  reason (at most 500 characters), and remove their override; the original verdict, author, time
  and history MUST be kept.
- **FR-029**: Dashboards (006), issue detection (009), review queues (007) and regression runs
  MUST use the overridden verdict; an override counts as a human label for that evaluator in
  calibration and takes precedence over the call-level label for that evaluator.
- **FR-030**: Re-running an evaluator MUST create a run without an override and note that the
  previous run was overridden.

**Memory probes (Story 7)**

- **FR-031**: A probe MUST be a persona simulation against a chosen version with planted facts
  (default 5, generated or entered), planted within the first 3 caller turns, and recall
  checkpoints (default turns 10, 20, 30 and 40; at most 50 caller turns), repeated 1 to 5 times
  (default 3).
- **FR-032**: A checkpoint MUST pass when the agent's reply states the fact; numbers, codes and
  dates MUST match exactly, other facts by a judge asked "does this reply state <fact>?".
- **FR-033**: The report MUST show each fact at each checkpoint per repetition, the last turn
  where every fact held, the first break turn (median and worst across repetitions) and the fact
  lost first. Checkpoints the call never reached are "not reached".
- **FR-034**: Before a probe starts, System MUST show the estimated cost and require confirmation.

**Fix confidence and safety caps (Story 8)**

- **FR-035**: Each validated fix MUST show a confidence: high when affected calls with verdicts
  are at least 10, improvement is at least `min_improvement` + 10 points, no evaluator regressed
  by more than 2 points and the headline evaluator's calibration reading is strong; low when
  affected calls are under 10 and the improvement is within 5 points of `min_improvement`, or
  calibration is untrusted or low; otherwise medium. The reasons MUST be listed.
- **FR-036**: A fix MUST be marked "Needs a human", with each reason in plain words, when any cap
  trips: its kind changes tools, transitions or knowledge-base attachments; it removes more than
  30% of the prompt text or adds more than 1,500 characters; it changes a sentence containing a
  protected term (default: disclosure, consent, recording, payment, card, legal; editable per
  workspace); confidence is not high; the regression set failed or was not run on the variant; or
  an automatic fix was applied to the agent in the last 7 days.
- **FR-037**: Agents MUST have an "auto-apply safe fixes" setting, off by default. When on, a fix
  with high confidence and no tripped cap MUST be applied as a new version, published only after
  its regression run passes, and the workspace told of the outcome. At most one automatic apply
  per agent per 7 days.

**Builder findings and policy checks (Story 9)**

- **FR-038**: On each draft save, System MUST run configuration checks that produce findings with
  a severity (blocker, warning, suggestion), the location (field, node, sentence), a reason and up
  to 2 proposed patches shown as before and after. Blockers are the existing validation errors.
- **FR-039**: The first release MUST include at least these checks: a tool named in a prompt but
  not attached; an attached tool never mentioned; a dynamic variable used but never supplied; a
  knowledge base attached with no instruction to search it; no instruction for ending the call; a
  flow node with no way out; a prompt over the model's recommended length.
- **FR-040**: An on-demand AI review MUST add findings for contradictory or vague instructions,
  billed as a feature charge once per request.
- **FR-041**: Applying a patch MUST change only the draft; dismissing MUST require a reason
  (not a problem, intended, other with a note) and the same finding stays dismissed until the
  located text changes.
- **FR-042**: For a knowledge-base document attached to the agent, users MUST be able to request
  up to 10 proposed checks, each quoting the passage verbatim (refused when the quote is not found
  in the document) with a draft custom judge question; accepting creates a custom evaluator
  (007), off until switched on.
- **FR-043**: A policy check MUST be marked "Source changed" when its passage no longer appears
  in the current document.

### Key Entities

- **Challenge Set**: the failing calls chosen for one applied issue, with their run inputs, mode
  and the baseline pass rate.
- **Regression Set**: per agent, the challenge sets of its applied issues; at most 100 calls.
- **Regression Run**: one batch of the regression set against one version; per-issue results,
  decision (passed, regressed, within tolerance, skipped with reason).
- **Rubric / Rubric Version**: the workspace's categories with score descriptions and critical
  flags.
- **Review**: one reviewer's rubric scores, notes and overall verdict on one call; kind (first,
  second pass, adjudication) and resolution.
- **Second-Pass Item**: a call waiting for a blind second review, with its reason (extreme,
  disputed, spot check).
- **Verdict Override**: a person's replacement verdict on one evaluator run, with reason, author,
  time and history.
- **Persona**: a reusable simulated caller: name, prompt, facts, voice, language.
- **Memory Probe**: a probe run's facts, checkpoints, repetitions and results per fact and turn.
- **Fix Assessment**: a fix revision's confidence, reasons and tripped caps.
- **Finding**: a configuration problem on an agent draft with severity, location, reason, patches
  and dismissal.
- **Policy Check Proposal**: a quoted passage from a document with a draft judge question and its
  status (proposed, accepted, rejected, source changed).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 95% of regression runs on sets of up to 100 calls finish within 15 minutes of the
  version being created; 100% of new versions of agents with a set show a result or a skip reason.
- **SC-002**: On a reference set where a version reverts a validated fix, the issue reopens in
  100% of cases; across 20 unchanged versions, at most 1 false reopen.
- **SC-003**: On a 40-recording reference set with known noise, clipping, loudness and voice
  quality, at least 95% of audio verdicts match the expected verdict, and 95% of calls have audio
  results within 3 minutes of the call ending.
- **SC-004**: A reviewer completes a rubric review of a 5-minute call in under 3 minutes (median).
- **SC-005**: In tests, zero second-pass reviewers can see the first review or evaluator verdicts
  before saving, and 100% of reviews meeting the second-pass rules enter the queue.
- **SC-006**: Within 1 minute of an override, every figure that uses the verdict reflects it.
- **SC-007**: An operator can create a persona and launch it against an agent in under 1 minute.
- **SC-008**: 95% of 40-turn memory probes (3 repetitions) produce a report within 10 minutes.
- **SC-009**: Zero automatically applied fixes trip a safety cap, checked by tests and a nightly
  audit.
- **SC-010**: On a 30-configuration reference set with planted defects, the configuration checks
  find at least 90% of the defects, and reviewers judge at most 10% of findings wrong.
- **SC-011**: 100% of accepted policy checks quote text present in the source document.

## Assumptions

- Evaluators, verdicts, labels, review queues and calibration come from 007; simulations,
  batches, personas in runs and datasets from 008; issues, fixes, validation and apply from 009.
- Each challenge call runs once per regression run; repeat runs and a flaky flag belong to
  release safety (018). The single re-run before reopening limits false reopens meanwhile.
- Release safety (018) may block publishing on a failing regression run; this spec only reports
  and reopens.
- Workspaces have one owner today; second pass and adjudication assume team members arrive with
  roles. Until then the single-member rule in FR-017 applies and adjudication falls to the owner.
- Default thresholds (20 dB, 0.5%, −16 ± 3 LUFS, 3.5 of 5, 10-point tolerance, 25% extreme,
  10% spot check) are Callwright's starting targets and are adjustable per agent or workspace.
- Text simulations cannot measure audio; audio-mode and stress-condition simulations are a later
  feature.
- Alerts for reopened issues are sent by outcome analytics (021).

## Out of Scope

- Audio-mode or noisy-condition simulations; before-and-after listening comparisons.
- Repeat runs as a release gate; human-score drift detection; root-cause breakdowns.
- Auto-apply of kinds other than prompt and guardrail edits; auto-apply without a regression set.
- Rubrics per agent (one rubric per workspace in this release).
- Pronunciation and voice tuning findings.
