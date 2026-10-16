---
description: "Task list for 009-issues-autofix"
---

# Tasks: Issues and Auto-Fix

**Input**: Design documents from `/specs/009-issues-autofix/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/issues.yaml,
quickstart.md; 008 phases 1-5 merged (batches, scorecard pairing, completion hook)

**Tests**: Required. Principle VII: contract tests for every operation; the keep rule, its
thresholds and boundaries, clustering determinism and fix application are written test-first.
Each test task must fail before its implementation task starts.

**Organization**: Grouped by user story (US1-US5 from spec.md).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1-US5; Setup, Foundational and Polish tasks carry no story label

---

## Phase 1: Setup

- [ ] T001 Create module package services/api/app/issues/ with empty `router.py`, `schemas.py`, `models.py`, `service.py`, `jobs.py`
- [ ] T002 Register the issues router under `/v1` in services/api/app/main.py and the arq jobs `detect_issues` and `finalize_validation` in services/api/app/core/jobs.py
- [ ] T003 [P] Add specs/009-issues-autofix/contracts/issues.yaml to the assembly list and regenerate contracts/openapi.yaml
- [ ] T004 [P] Regenerate the web client into apps/web/src/api/
- [ ] T005 [P] Add scikit-learn and numpy to services/api/pyproject.toml

---

## Phase 2: Foundational (blocks all stories)

- [ ] T006 Alembic migration services/api/app/migrations/versions/0090_issues.py: enums, tables in data-model.md, RLS policies, pgvector columns sized from 005's embedding dimension, partial unique index for running detections, trigger that rejects updates to completed `issue_validations` rows
- [ ] T007 [P] SQLAlchemy models Issue, IssueSample, IssueFailureEmbedding, IssueFix, IssueValidation, IssueDetectionRun in services/api/app/issues/models.py
- [ ] T008 [P] Pydantic schemas matching contracts/issues.yaml, FixPayload as a union discriminated by kind, in services/api/app/issues/schemas.py
- [ ] T009 [P] Unit test for the lifecycle state machine (every allowed transition, every refused one, final states) in services/api/tests/unit/test_issue_lifecycle.py
- [ ] T010 Transition function and guards to pass T009 in services/api/app/issues/service.py
- [ ] T011 [P] Unit test for charge keys and once-only charging of `issues.detect` and `issues.draft_fix` in services/api/tests/unit/test_issue_charges.py
- [ ] T012 Charge helper over `billing.charge_feature()` to pass T011 in services/api/app/issues/service.py
- [ ] T013 [P] Contract test for all operations in contracts/issues.yaml in services/api/tests/contract/test_issues_contract.py

**Checkpoint**: storage, schemas and lifecycle ready.

---

## Phase 3: User Story 1 - Find recurring problems (P1) MVP

**Goal**: detection, issue list and detail with samples, calibration warning.
**Independent Test**: quickstart section 1.

### Tests for User Story 1

- [ ] T014 [P] [US1] Unit test (test-first) for clustering: fixed vectors produce the same clusters on repeat; clusters under 3 distinct calls dropped; at most 20 new; turn failures collapse per call; grouping by evaluator and node in services/api/tests/unit/test_issue_clustering.py
- [ ] T015 [P] [US1] Unit test for matching: centroid similarity 0.85 boundary; open issue updated; dismissed issue counts only; applied issue with later-version calls yields recurrence in services/api/tests/unit/test_issue_clustering.py
- [ ] T016 [P] [US1] Integration test: seed 8 + 2 failures, detect, one issue of 8, re-detect creates none, concurrent detect 409, simulated scope marks origin, disabled evaluator ignored in services/api/tests/integration/test_issue_detection.py

### Implementation for User Story 1

- [ ] T017 [US1] Failure loader (window, scope, enabled evaluators, turn collapse) and grouping in services/api/app/issues/detection.py
- [ ] T018 [US1] Embedding with cache table via 005's adapter and agglomerative clustering to pass T014 in services/api/app/issues/detection.py
- [ ] T019 [US1] Matching and merge into existing issues, recurrence links, sample capping at 50 to pass T015 in services/api/app/issues/detection.py
- [ ] T020 [US1] Cluster naming LLM call (title, description, suspected cause) in services/api/app/issues/detection.py
- [ ] T021 [US1] `detect_issues` job (detection run row, counts, charge, calibration warning from 007) in services/api/app/issues/jobs.py
- [ ] T022 [US1] Endpoints detect, detection, list, get, samples in services/api/app/issues/router.py
- [ ] T023 [P] [US1] Issues page (agent picker, window 7/14/30/90, scope, detect with progress, status filter, list) in apps/web/src/routes/issues/IssuesPage.tsx
- [ ] T024 [US1] Issue detail page summary and samples with links to calls and calibration warning in apps/web/src/routes/issues/IssueDetailPage.tsx
- [ ] T059 [P] [US1] Integration test for list filters: `window_days` keeps only issues last seen in the window, `scope=real` hides mostly-simulated issues, combined with agent and status in services/api/tests/integration/test_issue_list_filters.py
- [ ] T060 [US1] Add the `window_days` filter (index on `(workspace_id, agent_id, last_seen_at)`) to the list query in services/api/app/issues/service.py and services/api/app/issues/router.py
- [ ] T061 [P] [US1] Issues page filter state: agent, status, window and source in the URL; every change refetches the list; window and source passed to Detect; Detect disabled with hint until an agent is chosen; readable status labels; web test asserting one list request per filter change in apps/web/src/routes/issues/IssuesPage.tsx and apps/web/src/routes/issues/IssuesPage.test.tsx

**Checkpoint**: US1 delivers a usable issue list on its own.

---

## Phase 4: User Story 2 - Drafted fixes (P1)

**Goal**: eight fix kinds, AI and manual revisions, diffs, advisory knowledge fixes.
**Independent Test**: quickstart section 2.

### Tests for User Story 2

- [ ] T025 [P] [US2] Unit test for allowed and recommended kinds per agent type and node attribution in services/api/tests/unit/test_issue_kinds.py
- [ ] T026 [P] [US2] Unit test (test-first) for `apply_fix` per kind: correct snapshot change, `redraft_needed` when current values differ, guardrail idempotency, add_transition label uniqueness, node_tool_attachment requires agent tools, kb_attach advisory, hash stable across key order in services/api/tests/unit/test_fix_application.py
- [ ] T027 [P] [US2] Integration test: AI draft picks allowed kind and charges once on retry; manual revision supersedes; drafting on a validated issue returns it to open in services/api/tests/integration/test_issue_validation.py

### Implementation for User Story 2

- [ ] T028 [P] [US2] Kind rules to pass T025 in services/api/app/issues/kinds.py
- [ ] T029 [US2] `apply_fix(snapshot, kind, payload)` with 002/004 validation and 008 canonical hash to pass T026 in services/api/app/issues/fixes.py
- [ ] T030 [US2] Drafting prompt and structured output (tagged union over allowed kinds, sample excerpts, guidance) in services/api/app/issues/fixes.py
- [ ] T031 [US2] Revision service (numbering, supersede rules, advisory status, diff via 002) in services/api/app/issues/service.py
- [ ] T032 [US2] Endpoints list and create fixes in services/api/app/issues/router.py
- [ ] T033 [P] [US2] Before/after diff rendering per kind in apps/web/src/routes/issues/FixDiff.tsx
- [ ] T034 [US2] Fix panel (kind picker with recommended first, guidance, draft, redraft, manual edit, revision history) in apps/web/src/routes/issues/FixPanel.tsx

---

## Phase 5: User Story 3 - Validate with simulations (P1)

**Goal**: control and treatment batches, keep rule, immutable evidence, draft-and-validate.
**Independent Test**: quickstart section 3 and the keep-rule fixtures.

### Tests for User Story 3

- [ ] T035 [P] [US3] Unit test (test-first) for the keep rule in services/api/tests/unit/test_validation_rule.py covering: control 2/10 vs treatment 6/10 passes (+40.0); control 4/20 vs treatment 5/20 (+5.0) fails `improvement_below_threshold`; control 2/10 vs treatment 3/10 (exactly +10.0) passes; other evaluator at exactly -5.0 does not block and at -8.0 blocks with `regression`; regression below `min_sample` reported as `insufficient_data` only; headline n = 4 with min_sample 5 is `inconclusive`; 3 of 10 treatment runs failed (30%) is `inconclusive`; headline regression on guard set blocks; custom thresholds respected; version mismatches excluded
- [ ] T036 [P] [US3] Integration test with stubbed 008 batches: validate moves to validating then validated; failing rule returns to open with evidence; cancel keeps attempt as cancelled; draft-and-validate failure keeps failed revision; evidence row cannot be updated after completion; dry run returns estimate only in services/api/tests/integration/test_issue_validation.py

### Implementation for User Story 3

- [ ] T037 [US3] Keep rule with `fractions.Fraction`, inclusive pass bounds and reason codes to pass T035 in services/api/app/issues/validation_rule.py
- [ ] T038 [US3] Call selection (affected live calls, simulated samples mapped to base calls, guard calls, retention filtering, not-enough-calls refusal) in services/api/app/issues/validation.py
- [ ] T039 [US3] Start validation: estimate via 008 pre-flight, create control and treatment batches with `source = issue_validation`, write running attempt, move issue in services/api/app/issues/validation.py
- [ ] T040 [US3] `finalize_validation` job on 008 completion hook: pair verdicts per set, run the rule, write evidence once, update revision and issue status in services/api/app/issues/jobs.py
- [ ] T041 [US3] Endpoints validate (with dry run), draft-and-validate, validations, validation/cancel in services/api/app/issues/router.py
- [ ] T042 [P] [US3] Validate dialog (estimate, mode, thresholds with allowed ranges) in apps/web/src/routes/issues/ValidateDialog.tsx
- [ ] T043 [US3] Evidence view (thresholds, headline, per-evaluator table by set, reasons, batch links, attempt history) in apps/web/src/routes/issues/ValidationEvidence.tsx

---

## Phase 6: User Story 4 - Apply as a new version (P2)

**Goal**: guarded apply, version with changelog link, tool copy for shared tools.
**Independent Test**: quickstart section 4.

- [ ] T044 [P] [US4] Integration test: apply creates and publishes a version whose hash equals `variant_config_hash`; release notes contain issue id and title; refused with `no_passing_validation`, `base_version_changed`, `draft_changed`, `wrong_status`; `publish: false` leaves the published version unchanged; shared tool is copied and other agents unchanged; concurrent publish during apply is serialised by the lock in services/api/tests/integration/test_issue_apply.py
- [ ] T045 [US4] Locked apply with precondition checks, tool copy via 005, version creation and publish via 002, draft update, hash verification in services/api/app/issues/apply.py
- [ ] T046 [US4] Apply endpoint and `apply_blockers` / `can_apply` on issue detail in services/api/app/issues/router.py
- [ ] T047 [US4] Apply action with blockers explained and confirmation (publish or create only) in apps/web/src/routes/issues/IssueDetailPage.tsx
- [ ] T048 [P] [US4] `applied_agent_version_id` filter on the list endpoint so the version history (002) can link back to the issue in services/api/app/issues/service.py

---

## Phase 7: User Story 5 - Dismiss and follow up (P3)

**Goal**: dismiss with reasons, no recreation, post-apply figures, recurrence.
**Independent Test**: quickstart section 5.

- [ ] T049 [P] [US5] Integration test: `other` needs a note, `duplicate` needs a target of the same agent, dismiss during validation cancels batches, dismissed issue not recreated by detection, post-apply figures appear at 10 calls in services/api/tests/integration/test_issue_dismiss.py
- [ ] T050 [US5] Dismiss service and endpoint in services/api/app/issues/service.py and services/api/app/issues/router.py
- [ ] T051 [US5] Post-apply tracking query (before and after windows, ready at 10 calls) in services/api/app/issues/service.py
- [ ] T052 [P] [US5] Dismiss dialog in apps/web/src/routes/issues/DismissDialog.tsx
- [ ] T053 [US5] Post-apply panel and recurrence link on the detail page in apps/web/src/routes/issues/IssueDetailPage.tsx

---

## Phase 8: Polish and Cross-Cutting

- [ ] T054 [P] RLS test: issues, samples, fixes, validations and detection runs deny cross-workspace access in services/api/tests/integration/test_rls_009.py
- [ ] T055 [P] Nightly audit query for SC-001 (every applied issue has a passing attempt with matching hash) in services/api/app/issues/jobs.py
- [ ] T056 [P] OpenTelemetry spans for detection and validation carrying `issue_id` and `agent_id` in services/api/app/issues/jobs.py
- [ ] T057 End-to-end test with the real textsim runner on a seeded agent (detect, draft, validate, apply) in services/api/tests/integration/test_issue_validation.py
- [ ] T058 Run quickstart.md end to end and fix drift

---

## Dependencies & Execution Order

- Phase 1 then Phase 2 block all stories. 008 phases 1-5 must be merged before US3.
- US1 (detection) has no story dependency.
- US2 needs issues to exist (US1 or fixture issues).
- US3 needs US2 (a current revision) and 008 batches.
- US4 needs US3 (passing evidence).
- US5 dismiss needs only Phase 2; post-apply figures need US4.
- Within each story: tests first and failing, then services, routers, UI.

## Parallel Example: User Story 3

```bash
Task: "Unit test for the keep rule in services/api/tests/unit/test_validation_rule.py"
Task: "Integration test with stubbed batches in services/api/tests/integration/test_issue_validation.py"
Task: "Validate dialog in apps/web/src/routes/issues/ValidateDialog.tsx"
```

## Implementation Strategy

- **MVP**: Phases 1-3 (detection and issue list): useful on its own as a ranked failure report.
- **Then**: US2 and US3 together (a fix is only shown as trustworthy once validated).
- **Then**: US4 (apply), then US5.

Task counts: Setup 5, Foundational 8, US1 11, US2 10, US3 9, US4 5, US5 5, Polish 5.
