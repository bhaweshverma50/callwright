---
description: "Task list for 007 Quality and Evaluations"
---

# Tasks: Quality and Evaluations

**Input**: Design documents from `specs/007-quality-evals/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md
**Depends on**: 006 (`CallQualityPort`, call drawer, dashboard), 003 (post-call pipeline,
`calls.service.set_analysis`), 002 (`llms` client, agent editor), 001 (`billing.charge_feature`)

**Tests**: Required by Principle VII. Scoring aggregation, call evaluation status, calibration math
and charge idempotency are test-first: write the test, see it fail, then implement. Every module
has a contract test.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US6 from spec.md

---

## Phase 1: Setup

- [x] T001 Add `google-re2` to services/api/pyproject.toml
- [x] T002 [P] Add settings `EVAL_JUDGE_MODEL`, `EVAL_CONCURRENCY=4`, `EVAL_TIMEOUT_S=60`, `CALIBRATION_MIN_SAMPLE=5` in services/api/app/core/config.py
- [x] T003 Create migration for `analysis_variables`, `call_analyses`, `evaluators`, `evaluator_versions`, `agent_eval_settings`, `evaluator_runs`, `evaluator_run_groups`, `evaluator_result_items`, `annotations`, RLS policies (built-in SELECT with `workspace_id IS NULL`), indexes, and replacement of `analytics.evaluator_verdicts_v` in services/api/app/migrations/versions/0701_quality_evals.py
- [x] T004 [P] Register routers for analysis_vars, evaluators, evals, annotations, review, calibration in services/api/app/main.py
- [x] T005 [P] Fake LLM client with fixture lookup by prompt hash for tests in services/api/tests/fakes/fake_llm.py
- [x] T072 [P] Add `av` (PyAV) and `numpy` to services/api/pyproject.toml and the API image system libraries in services/api/Dockerfile
- [x] T073 [P] Add settings `EVAL_JUDGE_MODELS` (first entry is the default judge) and `EVAL_JUDGE_PASS_CUTOFF=0.5` in services/api/app/core/config.py

---

## Phase 2: Foundational (blocks all stories)

- [x] T006 [P] Unit tests (write first) for run verdict aggregation (call scope, turn scope with `max_failed_items`, all n/a, mean score excludes n/a, process_reward -1/0/+1) and call eval status derivation in services/api/tests/unit/evals/test_scoring.py
- [x] T007 Implement pure scoring functions in services/api/app/evals/scoring.py
- [x] T008 [P] Evaluator protocol, `EvalContext` (transcript items, turn latencies, tool events, KB retrievals, flow transitions, agent version config) and `ItemResult` in services/api/app/evaluators/base.py
- [x] T009 [P] Judge framing (delimited data block, JSON output, server-side verdict from threshold, evidence index validation, empty-rationale retry) in services/api/app/evaluators/judge.py
- [x] T010 [P] Unit tests for judge framing and verdict derivation in services/api/tests/unit/evaluators/test_judge.py
- [x] T011 Contract test harness for `specs/007-quality-evals/contracts/*.yaml` in services/api/tests/contract/conftest.py (extend 006 harness)
- [x] T012 [P] Seed script for quickstart fixtures in services/api/scripts/seed_007.py
- [x] T074 Extend migration services/api/app/migrations/versions/0701_quality_evals.py with `evaluators.output_kind`, skip reason `not_sampled`, result item `start_ms`/`duration_ms`, and table `call_embeddings` (vector sized from 005's embedding dimension, HNSW cosine index, RLS)

**Checkpoint**: scoring is proven; judge plumbing exists.

---

## Phase 3: User Story 1 - Summary, sentiment and analysis variables (P1) MVP

**Independent Test**: quickstart section 2.

### Tests (write first)

- [x] T013 [P] [US1] Contract test for analysis_vars endpoints in services/api/tests/contract/test_analysis_vars_contract.py
- [x] T014 [P] [US1] Unit tests for variable validation (name regex, unique per agent, 25 limit, choice rules) in services/api/tests/unit/analysis_vars/test_service.py
- [x] T015 [P] [US1] Unit tests for extraction schema building and typed coercion (out-of-set choice becomes null, number parsing, unknown sentiment when caller silent) in services/api/tests/unit/analysis_vars/test_extractor.py
- [x] T016 [P] [US1] Unit tests for analysis charging (one charge per call attempt, skip on zero balance) in services/api/tests/unit/analysis_vars/test_charging.py

### Implementation

- [x] T017 [P] [US1] Models for `analysis_variables` and `call_analyses` in services/api/app/analysis_vars/models.py
- [x] T018 [US1] Variable CRUD, reorder and soft delete in services/api/app/analysis_vars/service.py
- [x] T019 [US1] Extractor (model from agent version, JSON schema from active variables, variable snapshot) in services/api/app/analysis_vars/extractor.py
- [x] T020 [US1] `analyze_call` and rerun jobs (balance check, `billing.charge_feature("post_call_analysis")`, write via `calls.service.set_analysis`) in services/api/app/analysis_vars/jobs.py
- [x] T021 [US1] Endpoints in services/api/app/analysis_vars/router.py and services/api/app/analysis_vars/schemas.py
- [x] T022 [US1] Hook `analyze_call` into the post-call pipeline step list (003 pipeline registry) in services/api/app/calls/pipeline.py
- [x] T023 [P] [US1] Variables editor (type picker, choices, description, reorder, extraction model note) in apps/web/src/routes/agents/quality/AnalysisVariablesEditor.tsx
- [x] T089 [P] [US1] Unit test: choices sent with `boolean`, `string` or `number` are rejected with a field error; `choice` needs 2 to 20 in services/api/tests/unit/analysis_vars/test_service.py
- [x] T090 [US1] "Add variable" form: live snake_case normalisation with the resulting name shown (`toVariableName()` in apps/web/src/routes/agents/quality/variableName.ts), choices field shown only for the fixed-set type, Save enabled only when FR-046 holds; web tests ("Customer Mood" saves as `customer_mood`, choices hidden for yes/no and number) in apps/web/src/routes/agents/quality/AddVariableDialog.tsx and apps/web/src/routes/agents/quality/AddVariableDialog.test.tsx
- [x] T024 [US1] Integration test: scripted harness call produces summary, sentiment and values in services/api/tests/integration/test_post_call_quality.py

---

## Phase 4: User Story 2 - Quality checks with verdicts and reasons (P1)

**Independent Test**: quickstart section 3.

### Tests (write first)

- [x] T025 [P] [US2] Contract tests for evaluators list/get and evals endpoints in services/api/tests/contract/test_evaluators_contract.py and services/api/tests/contract/test_evals_contract.py
- [x] T026 [P] [US2] Unit tests for effective settings (defaults, overrides validated against schema min/max/options, headline limit 4) in services/api/tests/unit/evals/test_settings.py
- [x] T027 [P] [US2] Unit tests for each of the 12 built-ins with fixtures (agent-type applicability, n/a cases, judge cutoff, process reward items) in services/api/tests/unit/evaluators/test_builtins.py
- [x] T028 [P] [US2] Unit tests for runner charging (one charge per run ID, free never charged, skip on zero balance mid-run) in services/api/tests/unit/evals/test_runner_charging.py
- [x] T029 [P] [US2] Integration test for rerun concurrency (second request 409, superseded runs kept, history returned) in services/api/tests/integration/test_rerun_concurrency.py
- [x] T030 [P] [US2] Injection suite (25 calls with spoken instructions; verdicts equal the clean variants) in services/api/tests/integration/test_judge_injection.py

### Implementation

- [x] T031 [P] [US2] Models for evaluators and versions in services/api/app/evaluators/models.py
- [x] T032 [P] [US2] Built-ins (catalog in data-model.md) in services/api/app/evaluators/builtins/anomaly_detection.py, factual_consistency.py, flow_completion.py, intent_fulfillment.py, kb_relevance.py, audio_silence.py, node_dead_end.py, process_reward.py, stuck_loop_detector.py, tool_call_correctness.py, transition_correctness.py, latency_slo.py
- [x] T033 [US2] Registry and startup sync (upsert built-ins, new version rows when `VERSION` rises) in services/api/app/evaluators/registry.py
- [x] T034 [US2] Catalog list/get endpoints in services/api/app/evaluators/router.py and services/api/app/evaluators/schemas.py
- [x] T035 [P] [US2] Models for settings, runs, run groups, result items in services/api/app/evals/models.py
- [x] T036 [US2] Effective settings and headline rules in services/api/app/evals/settings.py
- [x] T037 [US2] Runner (semaphore, timeout, one retry, progressive commits, `billing.charge_feature("eval.<name>")`, supersede on group completion) in services/api/app/evals/runner.py
- [x] T038 [US2] `evaluate_call` job and pipeline hook after analysis in services/api/app/evals/jobs.py and services/api/app/calls/pipeline.py
- [x] T039 [US2] Settings, evaluations and rerun endpoints in services/api/app/evals/router.py and services/api/app/evals/schemas.py
- [x] T040 [US2] `CallQualityPort` implementation (summary, list filter clause, window stats, headline set, verdict diff) and registration at startup in services/api/app/evals/quality_port.py and services/api/app/evals/verdict_diff.py
- [x] T041 [US2] Verdict diff endpoint in services/api/app/evals/router.py
- [x] T042 [P] [US2] Evaluator catalog and settings form generated from `settings_schema`, headline picker, cost badges in apps/web/src/routes/agents/quality/EvaluatorCatalog.tsx
- [x] T043 [P] [US2] Call drawer checks section (grouped verdicts, per-turn rows, summary chips, running state polling, rerun, history) in apps/web/src/routes/calls/quality/QualityChecks.tsx

### Catalog details from the live walkthrough (FR-033 to FR-043)

- [x] T075 [P] [US2] Golden catalog test: `GET /v1/evaluators?agent_type=flow` returns exactly the 12 built-ins with scope, cost class, output kind, default on/off and every settings field (type, min, max, default) equal to the data-model.md catalog table; `agent_type=single_prompt` returns the 8 non-flow ones, in services/api/tests/contract/test_builtin_catalog.py
- [x] T076 [P] [US2] Unit tests for `audio_silence` with synthetic dual-channel WAV fixtures (silence only on one channel is not silence, run shorter than `min_silence_ms` ignored, 3,000 ms boundary, leading and trailing silence excluded, no recording gives n/a) in services/api/tests/unit/evaluators/test_audio_silence.py
- [x] T077 [P] [US2] Unit tests for flow checks (`flow_completion` end and transfer, `node_dead_end` item per node, `stuck_loop_detector` 3 visits pass and 4 fail, `transition_correctness` seeded shuffle and per-source-node items) in services/api/tests/unit/evaluators/test_flow_checks.py
- [x] T078 [P] [US2] Unit tests for `anomaly_detection` with fixed vectors (threshold boundary, window filter, below `min_sample_size` gives insufficient data, backfill capped at `backfill_per_run`) and for `latency_slo` (item per agent turn, n/a for simulated calls) in services/api/tests/unit/evaluators/test_anomaly_latency.py
- [x] T079 [P] [US2] Unit tests for sampling (deterministic per call and evaluator, roughly 20 of 100 at 20%, not charged, skipped `not_sampled`, reruns and dataset and simulation triggers bypass) in services/api/tests/unit/evals/test_sampling.py
- [x] T080 [P] [US2] Unit tests for settings validation (int rejects 2.5, sample rate 150 rejected with field message, judge model outside the list rejected, unknown key rejected, out-of-range stored override clamped and reported in `adjusted_fields`) in services/api/tests/unit/evals/test_settings.py
- [x] T081 [US2] Recording reader (storage stream, PyAV decode, 20 ms frame levels per channel) in services/api/app/evaluators/audio.py
- [x] T082 [US2] Call embeddings (normalised call text, 005 embedding adapter, upsert, backfill, KNN query, zero-billable `embedding` usage) in services/api/app/evals/embeddings.py
- [x] T083 [US2] Deterministic sampling in services/api/app/evals/sampling.py and its use in services/api/app/evals/runner.py
- [x] T084 [US2] Judge model list endpoint, `options_source` fill, `{default}` helper rendering and field-level 422 errors in services/api/app/evaluators/router.py and services/api/app/evals/settings.py
- [x] T085 [P] [US2] Check cards for the quality tab: immediate save on toggle (full PUT with saved values), per-card Discard and Save settings, stepper for `int`, pick list for judge models, inline range errors that disable Save, helper text from the schema default; web tests for sample rate 150 and Discard in apps/web/src/routes/agents/quality/EvaluatorCard.tsx and apps/web/src/routes/agents/quality/EvaluatorCard.test.tsx

---

## Phase 5: User Story 3 - Label calls (P2)

**Independent Test**: quickstart section 4.

- [x] T044 [P] [US3] Contract test for annotations endpoints in services/api/tests/contract/test_annotations_contract.py
- [x] T045 [P] [US3] Model and upsert service (unique per user and call, note limit) in services/api/app/annotations/models.py and services/api/app/annotations/service.py
- [x] T046 [US3] Endpoints in services/api/app/annotations/router.py and services/api/app/annotations/schemas.py
- [x] T047 [P] [US3] "Your review" section (thumbs toggle, note with save/discard, teammates' labels) in apps/web/src/routes/calls/quality/YourReview.tsx

---

## Phase 6: User Story 4 - Calibration (P2)

**Independent Test**: quickstart section 5.

### Tests (write first, must fail before T051)

- [x] T048 [P] [US4] Unit tests for calibration math: 20-case reference table covering matrix counts, agreement, Wilson interval (k=6, n=10 gives about 0.313 to 0.832), reading bands at boundaries (n=4 insufficient, a=0.85 strong, a=0.5 not low, 2x ratio rules), label resolution (majority, tie is conflict), best threshold sweep with tie-breaking in services/api/tests/unit/calibration/test_math.py
- [x] T049 [P] [US4] Contract test for calibration endpoints in services/api/tests/contract/test_calibration_contract.py
- [x] T050 [P] [US4] Integration test: seeded 10-call fixture yields 4/2/2/2, 0.6, partial; simulated calls and other workspaces excluded; version scope current vs all in services/api/tests/integration/test_quality_isolation.py

### Implementation

- [x] T051 [US4] Pure functions in services/api/app/calibration/math.py
- [x] T052 [US4] Pair queries (current runs, resolved labels, per flow node rows, lookback, version scope) in services/api/app/calibration/service.py
- [x] T053 [US4] Endpoints in services/api/app/calibration/router.py and services/api/app/calibration/schemas.py
- [x] T054 [P] [US4] Calibration page (summary tiles, matrix cards greyed under 5, reading copy, threshold hint, version scope toggle, agent and lookback filters) in apps/web/src/routes/calibration/CalibrationPage.tsx

---

## Phase 7: User Story 5 - Custom evaluators (P2)

**Independent Test**: quickstart section 6.

- [x] T055 [P] [US5] Contract tests for custom create, patch, delete and trial in services/api/tests/contract/test_evaluators_contract.py
- [x] T056 [P] [US5] Unit tests for phrase check (required/forbidden, target speaker, plain text escaping, case sensitivity, invalid pattern 422, RE2 rejects backreferences) in services/api/tests/unit/evaluators/test_phrase_check.py
- [x] T057 [P] [US5] Unit tests for versioning (config edit bumps version, name-only edit does not, soft delete frees the name, 50 limit) in services/api/tests/unit/evaluators/test_custom_service.py
- [x] T058 [P] [US5] Phrase check evaluator in services/api/app/evaluators/custom/phrase_check.py
- [x] T059 [P] [US5] Custom judge evaluator (yes/no question, pass_when, model from catalog) in services/api/app/evaluators/custom/llm_judge_custom.py
- [x] T060 [US5] Custom CRUD, versioning, soft delete and trial (charged `eval.llm_judge_custom`, keyed by Idempotency-Key) in services/api/app/evaluators/service.py
- [x] T061 [US5] Custom and trial endpoints (declare `/evaluators/trial` before `/evaluators/{evaluator_id}`) in services/api/app/evaluators/router.py
- [x] T062 [P] [US5] Custom evaluator editor dialog with call picker and trial result in apps/web/src/routes/evaluators/CustomEvaluatorDialog.tsx
- [x] T086 [P] [US5] Unit tests for machine-name derivation from the display name (spaces and punctuation to underscores, leading digit handled, conflict reported on the derived name) and blank description stored as null in services/api/tests/unit/evaluators/test_custom_service.py
- [x] T087 [US5] Derive `name` from `display_name` when omitted in services/api/app/evaluators/service.py
- [x] T088 [P] [US5] Two-step "Add custom check" flow (template cards, form with Back, Create enabled only when name plus pattern or question are filled, judge model pick list from the judge model list) with web tests in apps/web/src/routes/evaluators/CustomCheckTemplatePicker.tsx and apps/web/src/routes/evaluators/CustomEvaluatorDialog.tsx

---

## Phase 8: User Story 6 - Review queue (P3)

**Independent Test**: quickstart section 7.

- [x] T063 [P] [US6] Contract test for review endpoints in services/api/tests/contract/test_review_contract.py
- [x] T064 [P] [US6] Unit and SQL tests for strategies (stable daily random order, failed ordering, disagreement closest split, teammate label does not hide, simulated calls excluded) and summary counts 12/7/4 in services/api/tests/unit/review/test_queue.py
- [x] T065 [US6] Queue and summary queries in services/api/app/review/service.py
- [x] T066 [US6] Endpoints in services/api/app/review/router.py and services/api/app/review/schemas.py
- [x] T067 [P] [US6] Review page (strategy tabs with counts, agent filter, cards, empty state, open drawer, "Next call") in apps/web/src/routes/review/ReviewPage.tsx

---

## Phase 9: Polish and cross-cutting

- [x] T068 [P] OpenTelemetry spans with `call_id` and `evaluator_name` in services/api/app/evals/runner.py and services/api/app/analysis_vars/jobs.py
- [x] T069 [P] Load test: calibration and review endpoints p95 < 1 s with 10,000 labelled calls in services/api/tests/integration/test_quality_perf.py
- [x] T070 [P] Extraction benchmark (30 calls, SC-005) with recorded fixtures in services/api/tests/integration/test_extraction_benchmark.py
- [x] T071 Run quickstart.md end to end and fix drift

---

## Dependencies and execution order

- Phase 1, then Phase 2 (scoring and judge plumbing) block all stories.
- US1 (analysis) and US2 (evaluators) are both P1 and independent of each other; US2's pipeline
  hook (T038) runs after US1's (T022) when both exist, otherwise directly after pricing.
- US3 (labels) needs only Phase 2.
- US4 (calibration) needs runs (US2) and labels (US3) in data, but its math (T048, T051) can be
  built in parallel from the start.
- US5 extends US2's catalog and runner.
- US6 needs US2 and US3 data.

## Parallel example: User Story 4

```bash
# Tests first, together
T048 unit/calibration/test_math.py, T049 contract/test_calibration_contract.py, T050 integration/test_quality_isolation.py
# Then
T051 calibration/math.py -> T052 calibration/service.py -> T053 router; T054 web page in parallel with T052
```

## Implementation strategy

1. Setup and Foundational.
2. US1 + US2 (MVP): every call gets analysis and verdicts with reasons; dashboard and call list
   light up through the port.
3. US3 then US4: labels and calibration close the trust loop.
4. US5 custom checks, then US6 review queue.
