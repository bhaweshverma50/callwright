# Feature Specification: Issues and Auto-Fix

**Feature Branch**: `009-issues-autofix`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Per-agent issue detection over a window (default 14 days, real or simulated calls) that clusters recurring evaluator failures; issue lifecycle open > validating > validated > applied | dismissed; LLM-drafted fixes of several kinds (prompt edit, node prompt edit, tool description edit, add guardrail, and others); validate by simulating the affected calls with the fix applied to a variant; auto-validate rule (keep only if the headline evaluator improves by at least 10 percentage points without regressing others beyond a threshold); apply creates a new agent version with a changelog link back to the issue; dismiss with reason. Nothing applies without validation evidence stored on the issue."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find the recurring problems of an agent (Priority: P1)

An operator opens Issues, picks an agent and runs detection over the last 14 days of real calls
(or 7, 30 or 90 days; optionally including simulated calls). The system groups evaluator
failures that share a cause into issues, each with a plain-language title ("Agent quotes prices
that are not in the price list"), a short description, the evaluator that flagged it, the flow
node involved (for flow agents), how many calls are affected, how many of them ran on the
current published version, and sample calls with the evaluator's reasoning for each. Running
detection again updates existing issues instead of creating duplicates.

**Why this priority**: Operators cannot read every failed verdict; a ranked list of recurring
problems is the entry point to the whole fix loop.

**Independent Test**: Seed 30 calls where 8 fail "Factual consistency" for the same reason and 2
fail it for an unrelated reason, run detection, and confirm one issue of 8 calls, no issue for
the 2-call group (below the minimum of 3), sample reasoning shown, and no duplicate after a
second detection.

**Acceptance Scenarios**:

1. **Given** an agent with failures in the window, **When** the operator runs detection with
   default settings, **Then** detection covers completed real calls from the last 14 days and the
   page shows progress until it finishes with counts of calls scanned and issues created or
   updated.
2. **Given** a detection already running for the agent, **When** another is requested, **Then**
   it is refused with a message that one is in progress.
3. **Given** an open issue from a previous detection, **When** detection finds the same failure
   pattern again, **Then** the existing issue gains the new sample calls and updated counts and
   no new issue is created.
4. **Given** the "Real + simulated" scope, **When** detection runs, **Then** issues built mostly
   from simulated calls are marked as such and the list filter can show or hide them.
5. **Given** an issue whose evaluator has low agreement with human labels in calibration,
   **When** the operator opens it, **Then** a warning says the evaluator may be wrong and links
   to calibration.
6. **Given** the Issues page with an agent chosen, **When** the operator changes the window from
   14 to 7 days or the source from "Real calls" to "Real + simulated", **Then** the list is
   fetched again and shows only issues seen within the chosen window and source, and the next
   detection uses the same window and source; the URL keeps all four filters so a reload shows
   the same list.
7. **Given** no agent is chosen, **When** the operator looks at the filter row, **Then** "Detect
   issues" is disabled with the hint "Choose an agent to run detection", and the status filter
   shows readable labels (All, Open, Validating, Validated, Applied, Dismissed).

---

### User Story 2 - Get a drafted fix for an issue (Priority: P1)

On an issue the operator asks for a fix. The system proposes a change of a kind that suits the
agent and the issue (for example, an edit to a flow node's instructions for a node-level issue),
explains why, and shows the change as a before/after diff. The operator can pick another kind,
add guidance ("keep the greeting unchanged"), redraft, or edit the proposal by hand. Each draft
is kept as a numbered revision.

**Why this priority**: The fix is what turns a finding into an improvement; without it the issue
list is a report.

**Independent Test**: For a single-prompt agent issue, draft a fix with no kind (system picks
"Prompt edit"), redraft with kind "Add guardrail" and guidance, then edit the guardrail text by
hand; confirm three revisions with diffs and that only the latest is current.

**Acceptance Scenarios**:

1. **Given** an open issue on a single-prompt agent, **When** the operator drafts without
   choosing a kind, **Then** the system returns a proposed fix of an allowed kind with a
   rationale and a before/after diff, and one feature charge is recorded.
2. **Given** a flow agent issue attributed to node "Collect address", **When** the operator opens
   the kind picker, **Then** only kinds allowed for node-level flow issues are offered, with the
   recommended one first.
3. **Given** a drafted fix, **When** the operator edits the proposed text and saves, **Then** a
   new revision with source "manual" becomes current and the previous one is kept as superseded.
4. **Given** an issue caused by missing knowledge where no knowledge base covers the topic,
   **When** an "Attach knowledge base" fix is drafted, **Then** it lists the uncovered topics,
   is marked advisory, and cannot be validated or applied.
5. **Given** a validated issue, **When** the operator drafts a new revision, **Then** the issue
   returns to open because the validated fix is no longer the current one.

---

### User Story 3 - Validate the fix with simulations before trusting it (Priority: P1)

The operator validates the current fix. The system builds a variant of the agent's published
version with the fix applied and simulates the affected calls twice: once against the unchanged
version (control) and once against the variant (treatment). It also simulates a small set of
recent calls that did not have the problem (guard calls) to catch side effects. It then applies
the keep rule: the headline evaluator's pass rate on the affected calls must improve by at least
10 percentage points over control, no other evaluator may drop by more than 5 percentage points
(on affected plus guard calls), and there must be enough completed simulations to judge. The
result, with every number, the thresholds used and links to both simulation batches, is stored
on the issue. "Draft and validate" does both steps in one action and keeps the fix only if it
passes.

**Why this priority**: Principle IV: a suggested fix is only trusted with evidence; this is the
step that makes auto-fix safe.

**Independent Test**: With a fixture where control passes 2 of 10 affected calls and treatment
passes 6 of 10 with no other evaluator dropping, validation passes; change treatment to 2 of 10
and it fails with the reason "improvement below threshold"; confirm evidence is stored either
way.

**Acceptance Scenarios**:

1. **Given** an open issue with a current fix, **When** the operator asks to validate, **Then**
   the system shows the number of simulations and the estimated cost, and on confirmation the
   issue moves to validating and links to the control and treatment batches.
2. **Given** control passes 20% and treatment 60% on the headline evaluator with no regression,
   **When** validation finishes, **Then** the issue moves to validated and the evidence shows
   +40.0 pp, the per-evaluator table and "passed".
3. **Given** treatment improves the headline evaluator by exactly 10.0 percentage points with no
   regression, **When** validation finishes, **Then** it passes.
4. **Given** the headline evaluator improves by 30 points but "Tool call correctness" drops by 8
   points with enough samples, **When** validation finishes, **Then** it fails, the issue returns
   to open, and the reason names the regressing evaluator and its drop.
5. **Given** fewer than 5 affected calls finish with a verdict in both arms, **When** validation
   finishes, **Then** the outcome is "inconclusive", the issue returns to open, and the fix cannot
   be applied.
6. **Given** "Draft and validate", **When** the drafted fix fails the rule, **Then** the issue
   stays open, the failed revision is kept with its evidence, and nothing is applied.

---

### User Story 4 - Apply a validated fix as a new agent version (Priority: P2)

On a validated issue the operator applies the fix. The system creates a new agent version from
exactly the configuration that passed validation, with release notes that name and link the
issue, publishes it so new calls use it (unless the operator chooses "create version only"), and
marks the issue applied with a link to the version. Apply is refused when there is no passing
validation for the current fix, or when the agent changed since validation.

**Why this priority**: Closes the loop; depends on US2 and US3.

**Independent Test**: Apply a validated fix and confirm the new version's content hash equals the
validated variant's, its release notes contain the issue id and title, the issue shows the
version, and a second apply is refused.

**Acceptance Scenarios**:

1. **Given** a validated issue, **When** the operator applies, **Then** a new version is created
   and published, its release notes read "Fix for <issue id>: <issue title>" with a link, and the
   issue becomes applied with the version id and time.
2. **Given** an open issue whose fix has never passed validation, **When** apply is requested
   (from any client), **Then** it is refused with "This fix has no passing validation".
3. **Given** a validated issue where someone published another version or saved draft changes
   after validation, **When** the operator applies, **Then** it is refused with a message to
   re-validate against the current version.
4. **Given** a "Tool description" fix on a tool that two other agents also use, **When** it is
   applied, **Then** the change goes to an agent-specific copy of the tool, the other agents are
   unaffected, and the apply summary says so.

---

### User Story 5 - Dismiss issues and follow up after a fix (Priority: P3)

The operator dismisses issues that are not worth fixing, choosing a reason (not a real problem,
evaluator is wrong, won't fix, duplicate of another issue, other with a note). Dismissed issues
are hidden by default and are not recreated by later detections. After a fix is applied, the
issue shows the headline evaluator's pass rate on real calls before and after the change once
enough calls have run, and if the same failure pattern comes back on the new version, detection
opens a new issue linked to the applied one.

**Why this priority**: Keeps the list clean and shows whether fixes held up; useful once the loop
is in regular use.

**Independent Test**: Dismiss an issue as duplicate of another, re-run detection, and confirm it
is not recreated; apply a fix, add 10 post-apply calls with known verdicts, and confirm the
before/after figures.

**Acceptance Scenarios**:

1. **Given** an open issue, **When** the operator dismisses it with reason "other" and no note,
   **Then** the dismissal is refused until a note is given.
2. **Given** a dismissed issue, **When** detection finds the same pattern, **Then** its counts
   update and it stays dismissed.
3. **Given** an issue applied 5 days ago with 12 real calls on the new version, **When** the
   operator opens it, **Then** it shows the headline pass rate on the previous version's calls
   in the window before apply and on the 12 new calls.
4. **Given** an applied issue, **When** the same failure pattern appears on calls of the new
   version, **Then** detection creates a new issue that links to the applied one as a
   recurrence.

---

### Edge Cases

- The agent has no evaluator failures in the window: detection completes with "No recurring
  failures found" and the window dates.
- Failures of evaluators that are now disabled are ignored by detection.
- Sample calls purged by retention: they drop out of the sample list; validation uses the
  remaining live calls and is refused with "not enough calls to validate" if fewer than the
  minimum sample remain.
- Issues built only from simulated calls: validation maps each simulated call to its base call;
  standalone persona simulations cannot be validated by base-call simulation and are skipped.
- Balance at or below zero: detection, drafting and validation are refused with an "add funds"
  message. Credit running out mid-validation makes it "inconclusive".
- The agent is deleted: its issues become read-only; open validations are cancelled.
- Validation is cancelled by the user or by a dismissal: the batches are cancelled, the attempt
  is kept with status "cancelled" and the issue returns to open (or stays dismissed).
- The fix no longer applies to the current configuration (for example, the node it edits was
  removed): validation and apply are refused with "redraft needed".
- An evaluator changed version between control and treatment results: affected pairs are left
  out and counted as version mismatches in the evidence.
- Two issues propose conflicting changes to the same prompt: each is validated against the
  version current at the time; applying one invalidates the other's evidence (base version
  changed), so it must be re-validated.

## Requirements *(mandatory)*

### Functional Requirements

**Detection**

- **FR-001**: System MUST run issue detection per agent over a window of 7, 14 (default), 30 or
  90 days on completed calls, using real calls only by default or real and simulated calls when
  asked, and allow at most one detection at a time per agent.
- **FR-002**: Detection MUST group failed evaluator verdicts from currently enabled evaluators by
  evaluator and flow node, cluster them by the similarity of the evaluator's reasoning, and keep
  clusters that cover at least 3 distinct calls, creating at most 20 new issues per detection.
- **FR-003**: Each issue MUST have a title (up to 80 characters), a description, the headline
  evaluator (name and version), the flow node (if any), affected call count, count on the current
  published version, first and last seen times, whether it comes mostly from simulated calls,
  and up to 50 sample calls with the evaluator's reasoning for each.
- **FR-004**: Detection MUST update a matching existing issue (same evaluator, same node, similar
  failure pattern) instead of creating a new one; it MUST NOT reopen dismissed issues; a match
  with an applied issue on calls of a later version MUST create a new issue linked as a
  recurrence.
- **FR-005**: System MUST show detection progress and its outcome (calls scanned, failures
  scanned, issues created, issues updated) and list issues filterable by agent, status and scope
  (real only, real and simulated), sorted by affected calls.
- **FR-006**: System MUST flag issues whose headline evaluator has low agreement with human
  labels (from calibration) once the calibration minimum sample is met.

**Fix drafting**

- **FR-007**: System MUST support these fix kinds:
  `prompt_edit` (replace the agent prompt), `node_prompt_edit` (replace one flow node's
  instructions), `add_guardrail` (append one rule to the agent prompt, to one node, or to every
  agent node), `tool_description_edit` (replace a tool's description), `transition_condition_edit`
  (replace one transition's condition), `add_transition` (new transition between two existing
  nodes with a condition), `node_tool_attachment` (attach or detach tools on one node) and
  `kb_attach` (attach existing knowledge bases, or list uncovered topics when none fits).
- **FR-008**: System MUST restrict kinds by agent type and issue attribution: single-prompt
  agents allow prompt_edit, add_guardrail, tool_description_edit and kb_attach; node-attributed
  flow issues allow node_prompt_edit, add_guardrail, transition_condition_edit, add_transition,
  node_tool_attachment, tool_description_edit and kb_attach; other flow issues allow
  add_guardrail, tool_description_edit and kb_attach. The recommended kind is prompt_edit,
  node_prompt_edit and add_guardrail respectively.
- **FR-009**: System MUST draft a fix with an LLM from the issue, its sample calls and the
  agent's published configuration, choosing a kind when none is given, with optional guidance,
  and return a rationale and a before/after diff.
- **FR-010**: Users MUST be able to enter or edit a fix by hand; every drafted or edited fix is
  stored as a new numbered revision; earlier revisions remain readable with their status.
- **FR-011**: A `kb_attach` fix that lists only uncovered topics MUST be marked advisory and MUST
  NOT be validated or applied.

**Validation**

- **FR-012**: System MUST validate the current fix revision by building a variant of the agent's
  published version with the fix applied and running two simulation batches over the same calls:
  control (published version unchanged) and treatment (variant). Calls are up to 20 affected live
  calls (default 20) plus up to 10 guard calls (recent completed live calls not in the issue that
  passed the headline evaluator, default 10). Default mode is persona; replay is selectable.
- **FR-013**: Before validation starts, System MUST show the number of simulations and the
  estimated cost and require confirmation.
- **FR-014**: The keep rule MUST pass only if all hold, using unrounded values:
  (a) at least `min_sample` (default 5) affected calls have a headline verdict in both arms;
  (b) headline pass rate on affected calls, treatment minus control, is at least
  `min_improvement` (default 10 percentage points);
  (c) for every other enabled evaluator over affected plus guard calls, and for the headline
  evaluator over guard calls, treatment minus control is not below minus `max_regression`
  (default 5 percentage points), counting only evaluators with at least `min_sample` pairs;
  (d) at most 20% of treatment runs failed. Failing (a) or (d) gives "inconclusive", failing (b)
  or (c) gives "failed".
- **FR-015**: Users MAY set `min_improvement` between 5 and 50 points, `max_regression` between 0
  and 20 points and `min_sample` between 3 and 50 per validation; the values used are stored.
- **FR-016**: Every validation attempt MUST be stored on the issue and never edited afterwards:
  fix revision, base version and its content hash, variant content hash, mode, thresholds, call
  ids of both sets, both batch ids, per-evaluator counts and changes for each set, decision,
  reasons, cost and times. The evidence MUST stay readable after the simulated calls are purged.
- **FR-017**: "Draft and validate" MUST draft a fix and validate it in one action; a fix that does
  not pass is kept as a failed revision and the issue returns to open.
- **FR-018**: Users MUST be able to cancel a running validation; the attempt is kept as cancelled.

**Lifecycle, apply and dismiss**

- **FR-019**: Issue status MUST follow: `open` to `validating` (validation starts); `validating`
  to `validated` (passed) or back to `open` (failed, inconclusive, cancelled, error); `validated`
  to `open` (a new revision becomes current) or `validating` (re-validate); `validated` to
  `applied`; `open`, `validating` or `validated` to `dismissed`. `applied` and `dismissed` are
  final.
- **FR-020**: Apply MUST be refused unless the issue is validated, the latest validation of the
  current revision passed, the agent's published version still equals the validation base
  version, and the agent's saved draft has no changes since that version.
- **FR-021**: Apply MUST create a new agent version whose configuration content hash equals the
  validated variant's hash, with release notes "Fix for <issue id>: <title>" linking to the issue,
  publish it unless "create version only" is chosen, and record the version id, time and user on
  the issue.
- **FR-022**: Apply of a `tool_description_edit` fix on a tool used by other agents MUST create an
  agent-specific copy of the tool with the new description and use it in the new version.
- **FR-023**: Dismiss MUST require a reason (`not_a_problem`, `evaluator_wrong`, `wont_fix`,
  `duplicate`, `other`), a target issue for `duplicate` and a note for `other`; dismissing during
  validation cancels it.
- **FR-024**: For applied issues, System MUST show the headline pass rate on real calls of the
  previous version in the window before apply and on real calls of the new version after apply,
  once at least 10 calls exist after apply.

**Billing**

- **FR-025**: Detection and drafting MUST be billed as feature charges (`issues.detect`,
  `issues.draft_fix`) once per request even when retried; validation is billed through the
  simulation and evaluation charges of its batches.

**Issues page filters** (added from the live walkthrough)

- **FR-026**: The issue list MUST be filtered on the server by agent, status, window and source,
  and every filter change MUST fetch the list again. Window (7, 14, 30 or 90 days) keeps issues
  last seen within the window; source "Real calls" hides issues built mostly from simulated
  calls and "Real + simulated" shows both. The same window and source MUST be used by the next
  detection, and all filters MUST be kept in the page address.
- **FR-027**: Detection MUST be unavailable until an agent is chosen, with a hint saying why; the
  status filter MUST show readable labels for each status while sending the status values.

### Key Entities

- **Issue**: a recurring failure pattern of one agent: title, description, headline evaluator,
  flow node, status, counts, sample calls, origin (real or simulated), calibration warning,
  applied version or dismissal details, recurrence link.
- **Issue Sample**: one failing call attached to an issue with the evaluator's reasoning and the
  version it ran on.
- **Fix Revision**: one proposed change: kind, payload with before/after values, rationale,
  source (AI or manual), base version, variant content hash, status (draft, validating, passed,
  failed, inconclusive, superseded, applied, advisory).
- **Validation Attempt**: immutable evidence for one validation of one revision: thresholds, call
  sets, batch links, per-evaluator results, decision and reasons.
- **Detection Run**: one execution of detection for an agent: window, scope, status, counts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of applied fixes have a passing validation attempt for the exact applied
  configuration (content hash match), checked by automated tests and a nightly audit query.
- **SC-002**: The keep rule gives the expected decision on every reference fixture, including the
  exact 10.0-point boundary, the 5.0-point regression boundary, and the minimum-sample boundary.
- **SC-003**: Detection over 14 days and up to 5,000 calls finishes within 3 minutes for 95% of
  runs.
- **SC-004**: Re-running detection on unchanged data creates zero new issues.
- **SC-005**: Fixes kept by validation reduce the headline evaluator's failure rate on real calls
  after apply in at least 70% of applied issues with 10 or more post-apply calls (tracked as a
  product metric).

## Assumptions

- Evaluator verdicts, versions, reasoning and calibration agreement come from quality evals
  (007); every verdict is pass or fail with an optional score.
- Simulations, batches and scorecards come from testing and simulation (008), including text-mode
  execution, mocks for tools and per-call verdict pairing.
- Agent versions (002) are complete snapshots (prompt, flow graph, tool definitions, knowledge
  base ids); a version can be created from a given snapshot and published in one step.
- Lint-style findings from static configuration checks are out of scope; issues come only from
  evaluator failures.
- Changes to evaluator settings (for example thresholds) are not fix kinds in v1; miscalibrated
  evaluators are handled through the calibration warning.
- Each call is simulated once per arm; the control arm removes the selection bias of comparing
  simulations with the failing originals.
- One user per workspace in v1; apply and dismiss need no role checks.
