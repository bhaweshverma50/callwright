# Implementation Plan: Issues and Auto-Fix

**Branch**: `009-issues-autofix` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-issues-autofix/spec.md`

## Summary

Turn evaluator failures into a short list of recurring issues per agent, draft a concrete fix
for each, prove the fix with simulations and only then apply it as a new agent version. A
detection job embeds and clusters failure reasons per evaluator and flow node, names each
cluster with one LLM call and merges it into existing issues. Fixes are typed payloads (eight
kinds) applied by one pure function to the published snapshot, producing the variant that 008
simulates. Validation runs a control batch and a treatment batch over the same affected and
guard calls, and a pure keep-rule module decides passed, failed or inconclusive from exact
fractions. The full evidence is written once to the issue. Apply re-checks that evidence
against the agent's current state inside a lock and creates the version through 002.

## Technical Context

**Language/Version**: Python 3.12 (API and jobs); TypeScript 5 (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, pgvector,
scikit-learn (agglomerative clustering), numpy; React, TanStack Query, React Router,
Tailwind + Radix, a text diff component (`diff` npm package) for before/after views
**Storage**: PostgreSQL 16 with RLS and pgvector (issue centroids, failure embedding cache)
**Testing**: pytest unit (keep rule, clustering, fix application, lifecycle), contract tests
against `contracts/issues.yaml`, integration tests with 008 batches stubbed at the experiment
service boundary and one end-to-end test with the textsim runner; Vitest for web
**Target Platform**: Linux containers (api, jobs); evergreen browsers
**Project Type**: Web application (SPA + API + jobs)
**Performance Goals**: detection over 14 days and 5,000 calls within 3 min p95; issue detail
read under 300 ms; keep-rule evaluation under 50 ms
**Constraints**: one running detection per agent; at most 20 new issues per detection; 50
samples stored per issue; validation uses at most 2 x 30 simulations
**Scale/Scope**: tens of issues per agent; 1 API module, 2 web routes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Provider-agnostic | Embeddings through 005's embeddings adapter; naming and drafting through the LLM adapter used by 002's prompt AI; models come from workspace settings. | PASS |
| II. Latency | No code on the live call path. Applied fixes change agent content only, never the runtime. | PASS (no hot-path change) |
| III. Metering | `issues.detect` and `issues.draft_fix` charged once per request via `billing.charge_feature()` keyed by detection run or `(issue_id, revision)`; validation cost flows through 008/007 charges of the two batches; estimate shown before validation; `Idempotency-Key` on paid POSTs. | PASS |
| IV. Measurability | Core of the feature: apply is impossible without a stored passing validation for the exact variant hash; evidence rows are immutable (trigger); control arm plus guard calls; evaluator versions recorded per row; post-apply tracking on real calls. | PASS |
| V. Tenancy and privacy | All tables RLS on `workspace_id`; samples and embeddings cascade on call purge; evidence keeps only ids and counts, not transcripts; fix drafting sends trimmed transcript excerpts only to the configured LLM provider of the workspace. | PASS |
| VI. Simplicity | One API module, jobs on the existing arq worker, no scheduler (post-apply figures computed on read). One new library (scikit-learn) instead of a hand-written clustering loop. | PASS |
| VII. Contracts and money | Contract tests for all 12 operations; keep-rule math, clustering determinism and fix application written test-first; charge idempotency tests. | PASS |

Post-design re-check: no violations; dependencies on 002, 005, 007 and 008 interfaces listed
under Integration Points.

## Project Structure

### Documentation (this feature)

```text
specs/009-issues-autofix/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── issues.yaml
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/issues/
├── router.py            public endpoints in contracts/issues.yaml
├── schemas.py           Pydantic models, FixPayload discriminated union by kind
├── models.py            Issue, IssueSample, IssueFailureEmbedding, IssueFix,
│                        IssueValidation, IssueDetectionRun
├── service.py           lifecycle transitions, listing, dismiss, post-apply figures
├── detection.py         load failures, embed, cluster, match, name
├── kinds.py             allowed and recommended kinds per agent type and attribution
├── fixes.py             apply_fix(snapshot, kind, payload) -> snapshot; drafting prompt
├── validation_rule.py   pure keep rule (Fraction math)
├── validation.py        select calls, start control/treatment batches via 008, evaluate rule
├── apply.py             locked apply, tool copy, version creation via 002
└── jobs.py              detect_issues, finalize_validation (on batch completion)
services/api/app/migrations/versions/0090_issues.py
services/api/tests/
├── unit/                test_validation_rule.py, test_issue_clustering.py,
│                        test_fix_application.py, test_issue_kinds.py,
│                        test_issue_lifecycle.py, test_issue_charges.py
├── contract/            test_issues_contract.py
└── integration/         test_issue_detection.py, test_issue_validation.py,
                         test_issue_apply.py, test_issue_dismiss.py, test_rls_009.py
apps/web/src/routes/issues/
├── IssuesPage.tsx       agent picker, window and scope controls, detect, list, filters
├── IssueDetailPage.tsx  summary, samples, fix panel, validation evidence, apply/dismiss
├── FixPanel.tsx         kind picker, guidance, draft/redraft, manual edit, revisions
├── FixDiff.tsx          before/after rendering per kind
├── ValidationEvidence.tsx  thresholds, headline, per-evaluator table, batch links
├── ValidateDialog.tsx   estimate and threshold settings
└── DismissDialog.tsx
```

**Structure Decision**: One API module `issues` and web routes `/issues` and `/issues/:id`, as
in the architecture.md ownership table. No worker code: simulations are delegated to 008.

## Integration Points

| Needs | Provided by | Interface used |
|---|---|---|
| Failed verdicts with reasoning, evaluator versions, enabled evaluators | 007 `evals` / `evaluators` | read queries over evaluator results by agent and window |
| Calibration agreement per evaluator | 007 `calibration` | `get_agreement(agent_id, evaluator_id)` |
| Full snapshot of a version, create and publish a version, draft hash, diff | 002 `agent_versions`, `agents` | `get_snapshot`, `create_version(snapshot, release_notes, publish)`, `draft_hash`, `diff` |
| Flow validation for variants | 004 `flows` | `validate_graph(snapshot.flow)` |
| Tool usage count and copy | 005 `tools` | `agents_using(tool_id)`, `copy_for_agent(tool_id, agent_id, overrides)` |
| Embeddings | 005 embeddings adapter | `embed(texts, model)` |
| Batches, scorecard pairs, canonical hash | 008 `simulator` | `start_experiment(..., source="issue_validation", issue_id)`, `pair_verdicts()`, `canonical_hash()`, completion hook |
| Feature charges | 001 `billing` | `charge_feature(workspace_id, feature, usage, ref)` |

Validation completion: 008 calls a registered hook when an experiment with
`source = issue_validation` finishes; `issues/jobs.py:finalize_validation` waits for both
batches, computes pairs and the rule, writes the attempt and moves the issue.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Control arm doubles validation simulations | Affected calls were selected for failing, so comparing with originals overstates every fix (research R2); Principle IV needs evidence that is not biased by construction | Original-vs-simulated comparison passes fixes that do nothing |
| New dependency scikit-learn in the API image | Deterministic agglomerative clustering with a distance threshold (FR-002, SC-004) | A hand-written average-linkage loop is more code to test and maintain |
