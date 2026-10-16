# Data Model: Testing and Simulation

**Feature**: 008-testing-simulation | **Date**: 2026-10-16

All tables carry `workspace_id` (FK `workspaces`) with row-level security
`workspace_id = current_setting('app.workspace_id')`. Timestamps are `timestamptz` in UTC.
IDs use the prefixes from architecture.md: `tc_`, `trn_`, `exp_`, `srun_`, `ds_`. Test results,
dataset items and categories use composite or natural keys, so no new prefixes are introduced.

## Enums

| Enum | Values |
|---|---|
| `test_status` | `passed`, `failed`, `error` |
| `run_status` | `queued`, `running`, `completed`, `failed`, `cancelled` (test runs) |
| `sim_status` | `pending`, `running`, `completed`, `failed`, `cancelled` (simulation runs and batches) |
| `sim_mode` | `replay`, `persona` |
| `target_type` | `published`, `draft`, `version`, `variant` |
| `missing_mock_policy` | `synthesize`, `error` |
| `answer_source` | `mock`, `recorded`, `synthesized`, `error` |
| `batch_source` | `call_selection`, `dataset`, `issue_validation`, `api` |
| `call_origin` (new, on `calls`) | `live`, `simulation` |
| `sim_end_reason` | `caller_turns_exhausted`, `caller_hung_up`, `agent_hangup`, `call_transfer`, `turn_limit_reached`, `error` |

## test_categories

| Field | Type | Rules |
|---|---|---|
| workspace_id | text | PK part |
| slug | text | PK part; `^[a-z][a-z0-9_]{1,39}$` |
| name | text | 1-60 chars |
| color | text | `^#[0-9a-f]{6}$`, one of the design palette tokens (`CATEGORY_PALETTE`); seeds get fixed palette entries; custom categories default to the first palette colour not yet used |
| is_seed | bool | seeds: `out_of_scope` "Out of scope", `bad_behaviour` "Bad behaviour", `identity` "Identity", `prompt_injection` "Prompt injection", `guardrails` "Guardrails" |
| created_at | timestamptz | |

Lists are ordered by `lower(name)` (FR-032). Seeds are inserted when a workspace is created (hook on 001's workspace creation) and by the
migration for existing workspaces. Seeds cannot be deleted; a custom category cannot be deleted
while test cases use it (409).

## test_cases (`tc_`)

| Field | Type | Rules |
|---|---|---|
| id | text | `tc_` ULID |
| workspace_id, agent_id | text | agent must exist in workspace |
| name | text | 1-120 chars; blank input becomes "<category name> test" |
| category_slug | text | FK (workspace_id, slug) |
| user_prompt | text | 1-2,000 chars |
| expected_behaviour | text | 1-2,000 chars |
| dynamic_variables | jsonb | object of string values, default `{}` |
| dedupe_key | text | sha256 of normalised user_prompt + expected_behaviour; unique per agent |
| last_status | test_status null | effective status of the latest completed run that included it |
| last_run_id | text null | `trn_` |
| created_at, updated_at | timestamptz | |

## test_runs (`trn_`)

| Field | Type | Rules |
|---|---|---|
| id | text | `trn_` ULID |
| workspace_id, agent_id | text | |
| target_type | target_type | `variant` not allowed here; default `draft` |
| agent_version_id | text null | set for `published` and `version` |
| config_snapshot | jsonb | resolved snapshot used |
| config_hash | text | sha256 hex |
| agent_model | text | model in the snapshot |
| judge_model | text | |
| status | run_status | |
| total, passed, failed, errored | int | counts use effective status; `passed + failed + errored <= total` |
| cost_usd | numeric(12,6) | from the feature charge |
| started_at, finished_at, created_at | timestamptz | |

Transitions: `queued > running > completed`; `queued|running > cancelled`;
`running > failed` (infrastructure error, all unfinished results become `error`).

## test_results (PK `test_run_id`, `test_case_id`)

| Field | Type | Rules |
|---|---|---|
| test_run_id | text | FK test_runs |
| test_case_id | text | not a FK (case may be deleted later) |
| workspace_id | text | |
| case_name, category_slug, user_prompt, expected_behaviour | text | copies taken at run start |
| agent_response | text null | |
| tool_calls | jsonb | `[{name, arguments, output, answer_source}]` |
| judge_status | test_status null | judge outcome; `error` on judge failure |
| judge_reasoning | text null | |
| override_status | `passed`/`failed` null | manual verdict |
| override_note | text null | up to 500 chars |
| overridden_at | timestamptz null | |
| effective_status | test_status | generated: `coalesce(override_status, judge_status)` |
| error_message | text null | |
| duration_ms | int null | |
| usage | jsonb | tokens per role (agent, judge) |

On override: recompute the run's counts and, if this run is the case's latest, the case's
`last_status`.

## simulation_experiments (`exp_`), shown in the UI as batches

| Field | Type | Rules |
|---|---|---|
| id | text | `exp_` ULID |
| workspace_id, agent_id | text | |
| name | text | default "Simulation <YYYY-MM-DD HH:mm>" |
| mode | sim_mode | |
| target_type | target_type | |
| agent_version_id | text null | for `published`/`version`; base version for `variant` |
| config_snapshot | jsonb | |
| config_hash | text | |
| variant_diff | jsonb null | `[{op, path, value, old}]` against the base version, for display |
| source | batch_source | |
| dataset_id | text null | when `source = dataset` |
| issue_id | text null | when `source = issue_validation` (set by 009) |
| settings | jsonb | `{max_caller_turns, missing_mock_policy, persona_model}` |
| status | sim_status | |
| total_count, completed_count, failed_count, cancelled_count | int | |
| cost_usd | numeric(12,6) | sum of run charges |
| error_message | text null | |
| created_at, finished_at | timestamptz | |

Status is derived after each run result: `running` while any run is pending or running;
`completed` when none are and at least one completed; `failed` when all failed; `cancelled`
after cancel once in-flight runs end. Validation: 2-100 base calls, all of the batch's agent,
all `origin = live`, status `completed`, transcript available.

## simulation_runs (`srun_`)

| Field | Type | Rules |
|---|---|---|
| id | text | `srun_` ULID |
| workspace_id, agent_id | text | |
| experiment_id | text null | FK simulation_experiments |
| base_call_id | text null | required for replay; optional for persona |
| mode | sim_mode | |
| target_type, agent_version_id, config_snapshot, config_hash | as above | copied from the batch reference for batch runs (snapshot stored once on the batch; run keeps hash) |
| persona_brief | jsonb null | `{goal, known_facts[], temperament, speaking_style, constraints[], opening_line?}` |
| persona_source | text null | `extracted` or `provided` |
| dynamic_variables | jsonb | from base call, else agent defaults, else request |
| settings | jsonb | as on batch |
| status | sim_status | |
| output_call_id | text null | FK calls (`origin = simulation`) |
| end_reason | sim_end_reason null | |
| diverged_at_turn | int null | replay only |
| answer_source_counts | jsonb | `{mock, recorded, synthesized, error}` |
| usage | jsonb | tokens per role (agent, caller, extraction, synth) |
| cost_usd | numeric(12,6) | |
| error_message | text null | |
| created_at, started_at, finished_at | timestamptz | |

Transitions: `pending > running > completed | failed`; `pending > cancelled`;
`running > cancelled` is not allowed (in-flight runs finish). Standalone persona runs
(`base_call_id` null) require `persona_brief`.

## calls (extension of the 003/006 table)

| Field | Type | Rules |
|---|---|---|
| origin | call_origin | default `live`, not null |
| simulation_run_id | text null | FK simulation_runs, set when `origin = simulation` |

Index `(workspace_id, agent_id, origin, ended_at desc)`. Simulated calls have no recording key,
no cost breakdown and no latency stats.

## datasets (`ds_`)

| Field | Type | Rules |
|---|---|---|
| id | text | `ds_` ULID |
| workspace_id, agent_id | text | |
| name | text | 1-80 chars; unique on `(workspace_id, lower(name))` (409 on conflict) |
| description | text null | up to 500 chars |
| item_count | int | maintained on add/remove |
| created_at, updated_at | timestamptz | |

## dataset_items (PK `dataset_id`, `call_id`)

| Field | Type | Rules |
|---|---|---|
| dataset_id | text | FK datasets on delete cascade |
| call_id | text | FK calls on delete cascade (retention purge removes the link) |
| workspace_id | text | |
| added_at | timestamptz | |

Add rules, checked per call in this order: unknown or other workspace (`not_found`), other agent
(`wrong_agent`), simulated (`simulated_call`), not completed (`not_completed`), transcript
purged (`unavailable`), already present (counted as duplicate). Cap 1,000 items per dataset.

## Computed: Scorecard (not stored; snapshot copied by 009 into validation evidence)

```
Scorecard {
  experiment_id, baseline: original | experiment, baseline_experiment_id?,
  base_call_count, sim_call_count, excluded_runs: [{simulation_run_id, status, error_message}],
  evaluators: [EvaluatorRow],
  by_node: [EvaluatorRow + {node_id, node_label}]
}
EvaluatorRow {
  evaluator_id, evaluator_name, evaluator_display_name, evaluator_version, scope,
  base_n, base_passes, base_pass_rate, sim_n, sim_passes, sim_pass_rate, delta_pp,
  base_mean_score, sim_mean_score,
  pairs: {n, improved, regressed, unchanged_pass, unchanged_fail, version_mismatch}
}
```

Rates are fractions in [0, 1] serialised with 4 decimals; `delta_pp` is serialised with 1
decimal; rules that compare against thresholds use `base_passes`, `base_n`, `sim_passes`, `sim_n`
directly (see research R8).
