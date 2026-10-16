# Implementation Plan: Testing and Simulation

**Branch**: `008-testing-simulation` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-testing-simulation/spec.md`

## Summary

Give operators three ways to check an agent before and after changes: single-turn test cases
judged by an LLM, text-mode simulations that replay a past call or let an LLM caller play a
persona against any target configuration, and datasets of calls used as regression suites.
Simulated conversations run through the same session code as live calls (a text-mode process
of the voice-worker image), tools answer from mocks, the result is stored as a call with
`origin = simulation` so 007's evaluators score it unchanged, and a pure scorecard module
compares verdicts between the original calls (or another batch) and the simulated ones. All
paid work goes through `billing.charge_feature()`.

## Technical Context

**Language/Version**: Python 3.12 (API, jobs, voice-worker); TypeScript 5 (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq (Redis), LiveKit
Agents (Python) session primitives in text mode; React, Vite, TanStack Query, React Router,
Tailwind + Radix, openapi-typescript client
**Storage**: PostgreSQL 16 with RLS (new tables in data-model.md; `calls` gains `origin` and
`simulation_run_id`); Redis for the `textsim` queue and per-workspace concurrency semaphore
**Testing**: pytest (unit, contract, integration), contract tests validate responses against
`specs/008-testing-simulation/contracts/*.yaml`; voice-worker offline harness
(`services/voice-worker/tests/harness/`); Vitest + Testing Library for web
**Target Platform**: Linux containers (api, jobs, voice-worker, voice-worker textsim role);
evergreen browsers
**Project Type**: Web application (SPA + API + workers)
**Performance Goals**: 20-case test run p95 under 2 min; 10-turn replay p95 under 60 s excluding
evaluators; scorecard for a 100-call batch returns in under 1 s
**Constraints**: No outbound network from simulations except LLM and knowledge-search paths;
per-workspace simulation concurrency default 10; batches 2-100 calls; datasets up to 1,000 calls
**Scale/Scope**: Up to ~1,000 simulation runs per workspace per day; 4 API modules, 1 worker
process role, 6 web screens/tabs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Provider-agnostic | Agent, judge, persona and stand-in LLM calls go through existing LLM adapters selected by config (`worker/adapters/llm/*`, 007's judge adapter). No vendor named in code paths of this feature. | PASS |
| II. Latency | No change to the live audio path. The worker's tool executor gains a mock-resolution wrapper that is only constructed when the session mode is `simulation`; the benchmark call set must show unchanged p50/p95 before merge (task T085). Simulated calls store no latency stats. | PASS (benchmark task listed) |
| III. Metering | Every test run, generation, simulation run, persona extraction and tool stand-in is metered and charged once per run via `billing.charge_feature()` keyed by run id; `Idempotency-Key` on all paid POSTs; simulated calls never create `call_charge` rows. | PASS |
| IV. Measurability | This feature is the measurement path: exact target snapshots with hashes, evaluator-version parity, stored rationale, scorecard with sample sizes and flip counts, consumed by 009 for fix validation. | PASS |
| V. Tenancy and privacy | All new tables have `workspace_id` with RLS; the textsim runner talks only to internal API endpoints with a service token and the API sets `app.workspace_id` from the run; persona briefs and simulated transcripts follow transcript encryption and retention; exports contain only test case text. | PASS |
| VI. Simplicity | No new service or queue technology. One new process role in the voice-worker image and one Redis queue name, justified below. Polling instead of push. | PASS with Complexity Tracking entry |
| VII. Contracts and money | Contract tests for all four fragments; scorecard math and charge idempotency written test-first; harness tests for replay, persona stop rules and the no-outbound-network guarantee. | PASS |

Post-design re-check (after data-model.md and contracts): no new violations. The `calls`
extension is additive and documented below.

## Project Structure

### Documentation (this feature)

```text
specs/008-testing-simulation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── test_cases.yaml
│   ├── test_runs.yaml
│   ├── simulator.yaml
│   └── datasets.yaml
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/
├── test_cases/        router.py, schemas.py, models.py, service.py, import_format.py, generate.py
├── test_runs/         router.py, schemas.py, models.py, service.py, judge.py, jobs.py
├── simulator/         router.py, schemas.py, models.py, service.py, targets.py, preflight.py,
│                      scorecard.py, comparison.py, internal_router.py, jobs.py
├── datasets/          router.py, schemas.py, models.py, service.py
└── migrations/versions/
    └── 0080_testing_simulation.py
services/api/tests/
├── unit/              test_scorecard.py, test_import_format.py, test_targets.py,
│                      test_test_run_counts.py, test_sim_charges.py, test_dataset_rules.py
├── contract/          test_test_cases_contract.py, test_test_runs_contract.py,
│                      test_simulator_contract.py, test_datasets_contract.py
└── integration/       test_test_run_flow.py, test_replay_flow.py, test_experiment_flow.py,
                       test_persona_flow.py, test_dataset_flow.py, test_rls_008.py
services/voice-worker/worker/
└── textsim/           entry.py, runner.py, replay_caller.py, persona_caller.py,
                       mock_tools.py, api_client.py
services/voice-worker/tests/harness/
                       test_textsim_replay.py, test_textsim_persona.py,
                       test_textsim_mocks.py, test_textsim_no_egress.py
apps/web/src/routes/
├── agents/testing/    TestCasesTab.tsx, TestCaseEditor.tsx, GenerateDialog.tsx,
│                      ImportDialog.tsx, TestRunPanel.tsx, ResultRow.tsx
├── simulations/       SimulationsPage.tsx, ExperimentPage.tsx, RunComparePage.tsx,
│                      ScorecardTable.tsx, StartSimulationDialog.tsx, PreflightDialog.tsx,
│                      PersonaBriefEditor.tsx, VariantEditor.tsx
└── datasets/          DatasetsPage.tsx, DatasetPage.tsx, AddToDatasetMenu.tsx
apps/web/src/api/      regenerated client (openapi-typescript)
```

**Structure Decision**: Follows architecture.md section 2. API modules match the ownership
table for 008 (`test_cases`, `test_runs`, `simulator`, `datasets`). The text runner sits in the
voice-worker codebase so live and simulated sessions share `pipeline.py`, `flow/` and `tools/`.
`StartSimulationDialog` and `AddToDatasetMenu` are exported for mounting in Call History (006)
and the call quality view (007); the comparison lives at `/simulations/runs/:runId`.

## Key Design Notes

- **Target resolution** (`simulator/targets.py`): resolves `published | draft | version |
  variant` to a full snapshot via 002's `agent_versions` service, validates variants with 002
  and 004 validators, computes the canonical-JSON SHA-256 hash and, for variants, a diff against
  the base version using 002's diff helper.
- **Run lifecycle**: API inserts run(s) and pre-creates the simulated `calls` row
  (`origin = simulation`, status `queued`), enqueues `textsim.run_simulation(srun_id)`. The
  runner fetches the spec, runs the session, streams events to `/v1/internal/calls/{id}/events`,
  then posts the result; the API marks the call `ended`, which starts the post-call pipeline
  with the simulation branch (no pricing, no ledger, no webhook), then charges the feature and
  ensures base-call evaluations at the same evaluator versions.
- **Scorecard** (`simulator/scorecard.py`): pure functions over verdict rows, using
  `fractions.Fraction`; the router only loads rows and serialises. 009 imports
  `compute_scorecard()` and `pair_verdicts()` directly.
- **Service interface for 009**: `simulator/service.py` exposes
  `start_experiment(workspace_id, agent_id, mode, target, base_call_ids, source, issue_id)`,
  `targets.canonical_hash(snapshot)`, and a completion-hook registry
  (`on_experiment_finished(source, callback)`) that fires once per batch when it reaches a final
  status; 009 registers `issues.jobs.finalize_validation` for `source = issue_validation`.
- **Test runs**: `test_runs/jobs.py` fans out one `textsim.run_single_turn` per case (bounded by
  the same semaphore), then `judge_result` jobs call 007's judge adapter through
  `test_runs/judge.py`; counts update atomically per result.
- **Concurrency**: Redis semaphore key `sim:sem:{workspace_id}`; limit from workspace settings
  (default 10). Jobs failing to acquire re-enqueue with 5 s defer.
- **Web**: TanStack Query with `refetchInterval: 3000` while any visible run is active; routes
  `/simulations`, `/simulations/:experimentId`, `/simulations/runs/:runId`, `/datasets`,
  `/datasets/:datasetId`; Testing tab content inside `/agents/:id/testing`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New process role `textsim` in the voice-worker image (not in architecture.md topology) | FR-011/FR-014 require simulated sessions to behave like live ones; Principle VII already requires an offline scripted-caller driver | Running the LLM loop in the API duplicates prompt assembly, flow transitions and tool calls, so simulations would drift from production behaviour |
| `calls.origin` and `calls.simulation_run_id` columns, and a simulation branch in the post-call pipeline (architecture.md sections 5 and 6 do not list them) | FR-018: evaluators (007) and issue detection (009) must score simulated conversations exactly as real ones | A separate transcript table forces two input paths into every evaluator and the clustering job |
| Comparison view at `/simulations/runs/:runId` while architecture.md assigns `/calls/:id/compare` to 006 | The view reads simulator data (008) that 006 cannot depend on (006 precedes 007 and 008) | Building it inside 006 inverts the dependency order; 006's route can redirect to the 008 view |
