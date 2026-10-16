# Implementation Plan: Quality and Evaluations

**Branch**: `007-quality-evals` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/007-quality-evals/spec.md`

## Summary

Add the measurement layer of Principle IV: per-agent analysis variables with post-call summary,
sentiment and typed extraction; a versioned evaluator catalog (seven built-ins plus phrase-check
and custom-judge templates); per-agent evaluator settings with up to 4 headline checks; evaluator
runs that store verdict, score, rationale, evaluator version and settings snapshot, with manual
re-runs that keep history; one label per user per call; a review queue with random, failed and
disagreement strategies; and calibration with a 2x2 matrix, Wilson interval, plain-language
reading, a 5-call minimum and a threshold sweep over stored scores. All post-call work runs as
idempotent arq jobs in the existing pipeline, model calls go through the `llms` client, and every
paid step is charged through `billing.charge_feature`.

## Technical Context

**Language/Version**: Python 3.12 (API and jobs), TypeScript 5 (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, `google-re2`; web:
React, TanStack Query, React Router, Tailwind + Radix
**Storage**: PostgreSQL 16 with RLS (seven new tables, one replaced view)
**Testing**: pytest (unit, contract with `openapi-core`, integration on Postgres with RLS), fake
LLM client with recorded fixtures; Vitest + Testing Library + MSW (web)
**Target Platform**: Linux containers; evergreen browsers
**Project Type**: web application (API service, jobs worker, SPA)
**Performance Goals**: analysis done within 60 s of call end for 95% of calls; all evaluators
within 3 min for 95%; calibration and review endpoints p95 < 1 s for 10,000 labelled calls
**Constraints**: every non-n/a result has a rationale and version; phrase patterns linear-time;
no evaluator decides pass/fail from model text alone for threshold checks (server derives verdict)
**Scale/Scope**: 6 API modules, 25 endpoints, 2 jobs, 2 web routes (`/review`, `/calibration`),
agent quality tab, quality sections in the call drawer

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design: PASS.*

| Principle | Gate | Status |
|---|---|---|
| I. Provider-agnostic | Judge and extraction calls go through the `llms` client (002); model ids come from agent config, evaluator versions or the LLM catalog. No vendor names in evaluator code. | PASS |
| II. Latency | Off the hot path: runs after `call.ended` in the jobs worker. Anomaly detection reads stored turn latencies; it never touches the live pipeline. | PASS |
| III. Metering | `post_call_analysis`, `eval.<name>` and `eval.llm_judge_custom` charged via `billing.charge_feature` keyed by run or request; skipped with `insufficient_credit` when balance <= 0; free evaluators never charge. | PASS |
| IV. Measurability | This feature is the measurement: runs keep rationale, evaluator version and settings snapshot; calibration exposes trust per evaluator and version. | PASS |
| V. Tenancy and privacy | RLS on every table; built-in catalog rows readable via `workspace_id IS NULL` SELECT policy only; transcripts passed to judges are not logged beyond the run record; replaced analytics view uses `security_invoker`. | PASS |
| VI. Simplicity | No new service or queue; calibration and queues computed on request; one guard table for concurrent reruns. | PASS |
| VII. Contracts and money | Contract tests for all 6 modules; scoring aggregation, call eval status, calibration math (matrix, agreement, Wilson, reading, threshold sweep, label resolution) and charge idempotency written test-first. | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/007-quality-evals/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── analysis_vars.yaml
│   ├── evaluators.yaml
│   ├── evals.yaml
│   ├── annotations.yaml
│   ├── review.yaml
│   └── calibration.yaml
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/
├── analysis_vars/
│   ├── router.py, schemas.py, models.py   # analysis_variables, call_analyses
│   ├── service.py                         # CRUD, limits, ordering
│   ├── extractor.py                       # schema from variables, model call, typed coercion
│   └── jobs.py                            # analyze_call(call_id); rerun
├── evaluators/
│   ├── router.py, schemas.py, models.py   # evaluators, evaluator_versions
│   ├── service.py                         # custom CRUD, versioning, soft delete, trial
│   ├── registry.py                        # built-in registry and startup sync
│   ├── base.py                            # Evaluator protocol, EvalContext, ItemResult
│   ├── judge.py                           # judge prompt framing, JSON output, verdict derivation
│   ├── builtins/intent_fulfillment.py, tool_call_correctness.py, kb_relevance.py,
│   │            factual_consistency.py, process_reward.py, anomaly_detection.py,
│   │            flow_step_completion.py
│   └── custom/phrase_check.py, llm_judge_custom.py
├── evals/
│   ├── router.py, schemas.py, models.py   # agent_eval_settings, evaluator_runs, result items, run groups
│   ├── settings.py                        # effective settings, schema validation, headline limit
│   ├── scoring.py                         # run verdict, call eval status (pure)
│   ├── runner.py                          # fan-out with semaphore, timeout, retry, charging
│   ├── jobs.py                            # evaluate_call(call_id, trigger, run_group_id)
│   ├── verdict_diff.py
│   └── quality_port.py                    # implements 006 CallQualityPort
├── annotations/
│   └── router.py, schemas.py, models.py, service.py
├── review/
│   └── router.py, schemas.py, service.py  # queue SQL and summary
├── calibration/
│   ├── router.py, schemas.py
│   ├── math.py                            # pure calibration functions
│   └── service.py                         # pair queries, label resolution, rows
└── migrations/versions/0701_quality_evals.py

services/api/tests/
├── unit/analysis_vars/ unit/evaluators/ unit/evals/ unit/calibration/ unit/review/
├── contract/test_analysis_vars_contract.py, test_evaluators_contract.py, test_evals_contract.py,
│   test_annotations_contract.py, test_review_contract.py, test_calibration_contract.py
└── integration/test_post_call_quality.py, test_rerun_concurrency.py, test_quality_isolation.py,
    test_judge_injection.py

apps/web/src/
├── routes/agents/quality/   # agent quality tab: variables editor, evaluator catalog, settings form, headline picker
├── routes/calls/quality/    # call drawer sections: checks (grouped, per-turn rows, rerun), your review
├── routes/review/           # ReviewPage, queue cards, next-call flow
├── routes/calibration/      # CalibrationPage, matrix card, threshold hint
└── routes/evaluators/       # custom evaluator editor with trial (opened from the quality tab)
```

**Structure Decision**: Module names and paths from architecture.md sections 2 and 3. The
agent quality tab lives under `routes/agents/quality/` and is mounted by 002's agent editor;
call-drawer sections under `routes/calls/quality/` are mounted by 006's drawer. The custom
evaluator editor is a dialog; `routes/evaluators/` holds its components, not a new page route.

## Phase 0 and Phase 1 outputs

- [research.md](./research.md): R1 to R11 (settings placement, versioning, built-in logic, judge
  framing, execution, charging, calibration math, queue ordering, safe patterns, port, call write).
- [data-model.md](./data-model.md): tables, constraints, derived rules, state transitions.
- [contracts/](./contracts/): one OpenAPI 3.1 fragment per module.
- [quickstart.md](./quickstart.md).

## Integration points

- **003**: post-call pipeline enqueues `analysis_vars.jobs.analyze_call` then
  `evals.jobs.evaluate_call` before `call_analyzed` webhook; exposes
  `calls.service.set_analysis(...)`; call events give tool calls, KB retrievals, turn timings.
- **002**: `llms` completion client; agent type; agent version config (`advanced.analysis_model`,
  `llm.model`, prompt, `kb_ids`, `tool_ids`) for judge context; agent editor mounts the quality tab.
- **005**: KB retrieval events per turn (chunks and scores) for `kb_relevance` and
  `factual_consistency`.
- **004**: flow node labels and instructions for `flow_step_completion`.
- **001**: `billing.charge_feature`, balance check, feature rates in the pricing catalog.
- **006**: implements `CallQualityPort`; replaces `analytics.evaluator_verdicts_v`; the port's verdict-diff
  operation (backed by `evals/verdict_diff.py`) fills `verdict_diffs` in 006's compare response,
  and `GET /v1/evals/verdict-diff` exposes the same data directly.
- **008**: creates runs with `trigger = dataset | simulation` through `evals.jobs.evaluate_call`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Separate `evaluator_versions` table | Principle IV requires the exact definition behind each verdict | A version integer alone cannot show what changed; a JSON column on runs duplicates definitions per run |
| `evaluator_run_groups` guard table | Enforces one active rerun per call across API replicas | Redis locks expire and are invisible to SQL; advisory locks do not survive the request-to-job hand-off |
| `google-re2` dependency | Linear-time matching for user-supplied patterns (FR-012) | Python `re` permits catastrophic backtracking; timeouts via threads are unreliable |
