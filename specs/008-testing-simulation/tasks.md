---
description: "Task list for 008-testing-simulation"
---

# Tasks: Testing and Simulation

**Input**: Design documents from `/specs/008-testing-simulation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required. Principle VII makes contract tests mandatory for every fragment and makes
scorecard math and charge idempotency test-first. Write each test task before the matching
implementation and confirm it fails.

**Organization**: Grouped by user story (US1-US5 from spec.md). Paths follow architecture.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1-US5; Setup, Foundational and Polish tasks carry no story label

---

## Phase 1: Setup

- [x] T001 Create module packages with empty `router.py`, `schemas.py`, `models.py`, `service.py` in services/api/app/test_cases/, services/api/app/test_runs/, services/api/app/simulator/, services/api/app/datasets/
- [x] T002 Register the four routers under `/v1` and the internal simulator and test-run routers under `/v1/internal` in services/api/app/main.py
- [x] T003 [P] Add the four fragments to the assembly list and regenerate contracts/openapi.yaml from specs/008-testing-simulation/contracts/*.yaml
- [x] T004 [P] Regenerate the web client from contracts/openapi.yaml into apps/web/src/api/
- [x] T005 [P] Create package skeleton services/voice-worker/worker/textsim/__init__.py and add the `textsim` process command to the voice-worker container entry (services/voice-worker/Dockerfile)

---

## Phase 2: Foundational (blocks all stories)

- [x] T006 Write Alembic migration services/api/app/migrations/versions/0080_testing_simulation.py: enums, all tables in data-model.md with RLS policies, `calls.origin` (default `live`) and `calls.simulation_run_id`, index `(workspace_id, agent_id, origin, ended_at desc)`, seed categories for existing workspaces
- [x] T007 [P] Unit test for canonical snapshot hashing and target resolution rules (published, draft, version, variant validation errors) in services/api/tests/unit/test_targets.py
- [x] T008 Implement target resolution, canonical JSON hash and variant diff in services/api/app/simulator/targets.py (calls 002 agent_versions and 004 flow validators) to pass T007
- [x] T009 [P] Unit test for feature-charge keys and once-per-run idempotency (`feature:<run id>`, retried charge is a no-op) in services/api/tests/unit/test_sim_charges.py
- [x] T010 Implement `charge_run()` helper wrapping `billing.charge_feature()` with feature keys `testing.run`, `testing.generate`, `simulation.replay`, `simulation.persona`, `simulation.persona_extraction`, `simulation.tool_synth` in services/api/app/simulator/service.py to pass T009
- [x] T011 Add the simulation branch to the post-call pipeline (skip pricing, ledger call charge and `call_analyzed` webhook when `origin = simulation`) in services/api/app/calls/jobs.py
- [x] T012 [P] Default `origin = live` filter on call list, dashboard and analytics queries with an `include_simulated` query flag in services/api/app/calls/service.py
- [x] T013 [P] Per-workspace Redis semaphore (`sim:sem:{workspace_id}`, default 10, re-enqueue with 5 s defer) in services/api/app/simulator/jobs.py
- [x] T014 [P] Internal API client (service token, spec fetch, events, result) in services/voice-worker/worker/textsim/api_client.py
- [x] T015 [P] Harness test: a simulation session never opens a socket outside the LLM adapter and internal API allow-list in services/voice-worker/tests/harness/test_textsim_no_egress.py
- [x] T016 [P] Harness test for tool answer order (mock, recorded, synthesized, error) and `answer_source` labelling in services/voice-worker/tests/harness/test_textsim_mocks.py
- [x] T017 Implement the simulation tool executor wrapper (no HTTP or webhook executors constructed; kb_search real; end_call and transfer end the session) in services/voice-worker/worker/textsim/mock_tools.py to pass T015 and T016
- [x] T018 Implement the text-mode session runner (builds the session from `pipeline.py` with text I/O, posts events to `/v1/internal/calls/{id}/events`) in services/voice-worker/worker/textsim/runner.py
- [x] T019 arq consumer for queue `textsim` with jobs `run_single_turn` and `run_simulation` in services/voice-worker/worker/textsim/entry.py

**Checkpoint**: a text session can run against any resolved snapshot with mocked tools.

---

## Phase 3: User Story 1 - Write and run test cases (P1) MVP

**Goal**: authored, generated and imported single-turn test cases, judged runs, manual override.
**Independent Test**: quickstart section 1 on an agent with no calls.

### Tests for User Story 1

- [x] T020 [P] [US1] Contract test for every operation in contracts/test_cases.yaml in services/api/tests/contract/test_test_cases_contract.py
- [x] T021 [P] [US1] Contract test for every operation in contracts/test_runs.yaml in services/api/tests/contract/test_test_runs_contract.py
- [x] T022 [P] [US1] Unit test for import parsing (wrapped and bare formats, 500-row cap, row errors with index and field, normalised duplicate detection, dry run) in services/api/tests/unit/test_import_format.py
- [x] T023 [P] [US1] Unit test for run counts with overrides (override wins, clearing restores judge verdict, errors never count as pass or fail, last_status follows latest run only) in services/api/tests/unit/test_test_run_counts.py
- [x] T024 [P] [US1] Integration test: create, generate, import, run, override, export in services/api/tests/integration/test_test_run_flow.py

### Implementation for User Story 1

- [x] T025 [P] [US1] SQLAlchemy models TestCategory and TestCase in services/api/app/test_cases/models.py
- [x] T026 [P] [US1] SQLAlchemy models TestRun and TestResult (generated `effective_status`) in services/api/app/test_runs/models.py
- [x] T027 [US1] Pydantic schemas matching contracts/test_cases.yaml in services/api/app/test_cases/schemas.py
- [x] T028 [US1] Import and export format to pass T022 in services/api/app/test_cases/import_format.py
- [x] T029 [US1] Category and case service (default name rule, seed protection, dedupe key, workspace-creation seed hook) in services/api/app/test_cases/service.py
- [x] T030 [US1] AI drafting of test cases from the agent snapshot, charged as `testing.generate` in services/api/app/test_cases/generate.py
- [x] T031 [US1] Test cases router (CRUD, categories, import, export, template, generate) in services/api/app/test_cases/router.py
- [x] T032 [US1] Pydantic schemas matching contracts/test_runs.yaml in services/api/app/test_runs/schemas.py
- [x] T033 [US1] Judge prompt, structured-output parse and single retry via 007's judge adapter in services/api/app/test_runs/judge.py
- [x] T034 [US1] Run service (precondition checks, case selection, snapshot, counts, override recompute to pass T023) in services/api/app/test_runs/service.py
- [x] T035 [US1] Jobs: fan out `run_single_turn`, `judge_result`, finalize run and charge `testing.run` in services/api/app/test_runs/jobs.py
- [x] T036 [US1] Public and internal routers (start, list, get, cancel, override, export, spec, result) in services/api/app/test_runs/router.py
- [x] T037 [US1] Single-turn mode in the runner (agent greeting when agent speaks first, one caller turn, capture reply and tool calls) in services/voice-worker/worker/textsim/runner.py
- [ ] T038 [P] [US1] Testing tab list with category filter, last status chips and empty-prompt guard in apps/web/src/routes/agents/testing/TestCasesTab.tsx
- [ ] T039 [P] [US1] Case editor dialog in apps/web/src/routes/agents/testing/TestCaseEditor.tsx
- [ ] T040 [P] [US1] Generate dialog with draft review and save in apps/web/src/routes/agents/testing/GenerateDialog.tsx
- [ ] T041 [P] [US1] Import dialog with dry-run preview and template download in apps/web/src/routes/agents/testing/ImportDialog.tsx
- [ ] T042 [US1] Run panel with polling, summary toast, result rows with judge reasoning, tool calls and manual override in apps/web/src/routes/agents/testing/TestRunPanel.tsx and apps/web/src/routes/agents/testing/ResultRow.tsx
- [ ] T090 [US1] Category colour and ordering: extend migration services/api/app/migrations/versions/0080_testing_simulation.py with `test_categories.color` (seed palette values), `CATEGORY_PALETTE` in services/api/app/test_cases/service.py, order by `lower(name)` in list queries, and colour chips plus preselected category in apps/web/src/routes/agents/testing/TestCaseEditor.tsx
- [ ] T091 [P] [US1] Web test for the Generate dialog (25 becomes 20, 0 becomes 1, singular and plural action label, "All categories" sends `category: null`) in apps/web/src/routes/agents/testing/GenerateDialog.test.tsx
- [x] T092 [P] [US1] Harness test: single-turn test case on a flow agent enters at the start node, follows a transition and reports visited nodes in services/voice-worker/tests/harness/test_textsim_single_turn_flow.py

**Checkpoint**: US1 works on its own (no call history required).

---

## Phase 4: User Story 2 - Replay one call against a target (P1)

**Goal**: individual replay runs with pre-flight, mocks, divergence and side-by-side comparison.
**Independent Test**: quickstart section 2.

### Tests for User Story 2

- [x] T043 [P] [US2] Contract test for simulation-run, preflight, comparison and internal operations in contracts/simulator.yaml in services/api/tests/contract/test_simulator_contract.py
- [x] T044 [P] [US2] Unit test (test-first) for verdict collapse and pairing: turn scope fails if any turn fails, error and not_applicable excluded, version mismatch excluded, improved/regressed/unchanged classification in services/api/tests/unit/test_scorecard.py
- [x] T045 [P] [US2] Harness test for replay turn alignment, agent-first and caller-first starts, interrupted fragment merge, divergence turn, stop reasons in services/voice-worker/tests/harness/test_textsim_replay.py
- [x] T046 [P] [US2] Integration test: preflight, start, idempotent retry, completion, simulated call evaluated, base call evaluated at same evaluator version, one charge and no call charge in services/api/tests/integration/test_replay_flow.py

### Implementation for User Story 2

- [x] T047 [P] [US2] SQLAlchemy models SimulationExperiment and SimulationRun in services/api/app/simulator/models.py
- [x] T048 [US2] Pydantic schemas matching contracts/simulator.yaml in services/api/app/simulator/schemas.py
- [x] T049 [US2] Verdict collapse and pairing functions (`collapse_verdicts`, `pair_verdicts`) with `fractions.Fraction` to pass T044 in services/api/app/simulator/scorecard.py
- [x] T050 [US2] Pre-flight (tools and webhook nodes without mocks, invalid calls, run count, cost estimate from pricing) in services/api/app/simulator/preflight.py
- [x] T051 [US2] Run service: validate base call, resolve target, pre-create simulated call, enqueue, handle result, charge, ensure base-call evaluation via 007 in services/api/app/simulator/service.py
- [x] T052 [US2] Comparison builder (transcripts, node paths, unused caller turns, verdict diffs) in services/api/app/simulator/comparison.py
- [x] T053 [US2] Public router (preflight, simulation-runs CRUD-lite, comparison, cancel) in services/api/app/simulator/router.py
- [x] T054 [US2] Internal router (spec with caller turns, recorded tool outputs and original node path; result) in services/api/app/simulator/internal_router.py
- [x] T055 [US2] Replay caller (turn queue, divergence detection) to pass T045 in services/voice-worker/worker/textsim/replay_caller.py
- [ ] T056 [P] [US2] Start dialog with mode, target picker (published, draft, version, variant) and pre-flight step in apps/web/src/routes/simulations/StartSimulationDialog.tsx and apps/web/src/routes/simulations/PreflightDialog.tsx
- [ ] T057 [P] [US2] Variant editor (edit prompt, node instructions and tool descriptions of a copy of the base snapshot) in apps/web/src/routes/simulations/VariantEditor.tsx
- [ ] T058 [US2] Comparison page at `/simulations/runs/:runId` with side-by-side transcripts, answer-source badges, node paths and verdict table in apps/web/src/routes/simulations/RunComparePage.tsx
- [ ] T059 [US2] Mount StartSimulationDialog in the call quality view and Call History row actions (owned by 006/007) in apps/web/src/routes/calls/CallsPage.tsx

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: User Story 3 - Batch simulation and scorecard (P2)

**Goal**: batches from a call selection, progress, cancel, scorecard by evaluator and node,
batch-vs-batch baseline.
**Independent Test**: quickstart section 3 plus hand-checked scorecard fixture.

### Tests for User Story 3

- [x] T060 [P] [US3] Unit test (test-first) for scorecard aggregation: spec fixture 4/10 vs 7/10 gives +30.0 pp with 3 improved and 0 regressed; n = 0 gives null rates; failed runs excluded and listed; by-node grouping; mean score; experiment baseline matched by base call id; rounding half away from zero at display only, in services/api/tests/unit/test_scorecard.py
- [x] T061 [P] [US3] Contract test for experiment operations and scorecard schema in services/api/tests/contract/test_simulator_contract.py
- [x] T062 [P] [US3] Integration test: mixed-agent selection refused, 10-call batch, 2 failed runs, cancel mid-batch charges only finished runs, idempotent start in services/api/tests/integration/test_experiment_flow.py

### Implementation for User Story 3

- [x] T063 [US3] `compute_scorecard()` (per evaluator, per node, baseline original or experiment) to pass T060 in services/api/app/simulator/scorecard.py
- [x] T064 [US3] Experiment service (validation 2-100 calls of one agent, single snapshot, bulk insert runs, counters, derived status, cancel, `start_experiment()` callable by 009 with `source` and `issue_id`, completion-hook registry fired once per finished batch) in services/api/app/simulator/service.py
- [x] T065 [US3] Experiment endpoints (create, list, get, runs, scorecard, cancel) in services/api/app/simulator/router.py
- [ ] T066 [P] [US3] Simulations page with Batch and Individual tabs, agent filter and polling in apps/web/src/routes/simulations/SimulationsPage.tsx
- [ ] T067 [US3] Batch page with progress, runs list, scorecard by evaluator and by node, baseline switcher and cancel in apps/web/src/routes/simulations/ExperimentPage.tsx and apps/web/src/routes/simulations/ScorecardTable.tsx
- [ ] T068 [US3] "Run simulation" on Call History multi-select (one-agent check, pre-flight, start batch) in apps/web/src/routes/calls/CallsPage.tsx
- [ ] T093 [US3] Server-side agent filter and paging on the Simulations page (agent change refetches `GET /v1/experiments?agent_id=` and `GET /v1/simulation-runs?agent_id=&standalone=`, totals in tab labels, filter kept in the URL) with a web test that asserts a request per filter change in apps/web/src/routes/simulations/SimulationsPage.tsx and apps/web/src/routes/simulations/SimulationsPage.test.tsx

**Checkpoint**: batches and scorecards available to 009.

---

## Phase 6: User Story 4 - Persona simulations (P2)

**Goal**: persona extraction, LLM caller, standalone briefs.
**Independent Test**: quickstart section 4.

- [x] T069 [P] [US4] Harness test for the persona caller (follows brief, `hang_up` tool ends session, turn limit default 20 and max 50, never speaks as the agent) in services/voice-worker/tests/harness/test_textsim_persona.py
- [x] T070 [P] [US4] Integration test: persona from base call stores extracted brief; standalone brief run has null original side; charges `simulation.persona` and `simulation.persona_extraction` in services/api/tests/integration/test_persona_flow.py
- [x] T071 [US4] Persona extraction (JSON schema output, metered) in services/api/app/simulator/service.py
- [x] T072 [US4] Persona caller (brief prompt, `hang_up(reason)`, temperature 0.7, persona model from settings) to pass T069 in services/voice-worker/worker/textsim/persona_caller.py
- [ ] T073 [US4] Persona brief editor (view extracted brief, write a standalone brief) in apps/web/src/routes/simulations/PersonaBriefEditor.tsx
- [ ] T094 [US4] "New simulation" action on the Simulations page (agent picker, PersonaBriefEditor, pre-flight, start standalone persona run) in apps/web/src/routes/simulations/NewSimulationDialog.tsx and apps/web/src/routes/simulations/SimulationsPage.tsx

---

## Phase 7: User Story 5 - Datasets (P3)

**Goal**: datasets per agent, add/remove items, bulk evaluate, batch from dataset.
**Independent Test**: quickstart section 5.

- [x] T074 [P] [US5] Contract test for every operation in contracts/datasets.yaml in services/api/tests/contract/test_datasets_contract.py
- [x] T075 [P] [US5] Unit test for add-item rules and reason order, case-insensitive name uniqueness and the 1,000-item cap in services/api/tests/unit/test_dataset_rules.py
- [x] T076 [P] [US5] Integration test: create, add with duplicates and wrong agent, remove, evaluate, delete keeps calls, batch from dataset records `dataset_id` in services/api/tests/integration/test_dataset_flow.py
- [x] T077 [P] [US5] SQLAlchemy models Dataset and DatasetItem in services/api/app/datasets/models.py
- [x] T078 [US5] Pydantic schemas matching contracts/datasets.yaml in services/api/app/datasets/schemas.py
- [x] T079 [US5] Dataset service (rules to pass T075, item_count maintenance, bulk evaluate via 007 with `only_missing`) in services/api/app/datasets/service.py
- [x] T080 [US5] Datasets router in services/api/app/datasets/router.py
- [x] T081 [US5] Accept `dataset_id` as the call source in experiment creation in services/api/app/simulator/service.py
- [ ] T082 [P] [US5] Datasets list and create dialog in apps/web/src/routes/datasets/DatasetsPage.tsx
- [ ] T083 [US5] Dataset page with items, unavailable markers, remove, evaluate and "Run simulation" in apps/web/src/routes/datasets/DatasetPage.tsx
- [ ] T084 [US5] "Add to dataset" menu (pick or create inline, report skipped) mounted in the call quality view in apps/web/src/routes/datasets/AddToDatasetMenu.tsx
- [ ] T095 [US5] "New dataset" form with required agent picker and per-field messages on submit (name, agent, server 409 shown under name), and paged dataset items with total, plus web tests, in apps/web/src/routes/datasets/NewDatasetDialog.tsx, apps/web/src/routes/datasets/DatasetPage.tsx and apps/web/src/routes/datasets/NewDatasetDialog.test.tsx

---

## Phase 8: Polish and Cross-Cutting

- [ ] T085 Run the latency benchmark call set against the voice-worker with the textsim changes merged and attach p50/p95 to the PR (Principle II) using services/voice-worker/tests/harness/
- [x] T086 [P] RLS test: every 008 table and endpoint denies cross-workspace access, including internal endpoints with a mismatched run in services/api/tests/integration/test_rls_008.py
- [x] T087 [P] Retention hook: purge persona briefs and simulated transcripts with the base call; mark dataset items unavailable in services/api/app/simulator/jobs.py
- [x] T088 [P] OpenTelemetry spans for runs carrying `simulation_run_id` and `call_id` in services/voice-worker/worker/textsim/runner.py
- [ ] T089 Run quickstart.md end to end and fix drift

---

## Dependencies & Execution Order

- Setup (T001-T005) then Foundational (T006-T019) block all stories.
- US1 (Phase 3) and US2 (Phase 4) can proceed in parallel after Phase 2.
- US3 depends on US2 (runs, comparison, pairing functions in scorecard.py).
- US4 depends on US2 (run service and runner); independent of US3.
- US5 depends on Phase 2 for models and on US3 only for T081 (batch from dataset).
- Polish after the stories in scope.
- Within a story: tests first and failing, then models, services, routers, UI.

## Parallel Example: User Story 2

```bash
Task: "Contract test for simulation-run operations in services/api/tests/contract/test_simulator_contract.py"
Task: "Unit test for verdict collapse and pairing in services/api/tests/unit/test_scorecard.py"
Task: "Harness test for replay alignment in services/voice-worker/tests/harness/test_textsim_replay.py"
Task: "Start dialog in apps/web/src/routes/simulations/StartSimulationDialog.tsx"
Task: "Variant editor in apps/web/src/routes/simulations/VariantEditor.tsx"
```

## Implementation Strategy

- **MVP**: Phases 1-3 (test cases). Needs no call history and gives value on day one.
- **Next**: US2 then US3, which unlock 009 (issue validation needs batches and scorecards).
- **Then**: US4 (persona, also used by 009 by default) and US5 (datasets).

Task counts: Setup 5, Foundational 14, US1 26, US2 17, US3 10, US4 6, US5 12, Polish 5.
