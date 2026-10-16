# Data Model: Quality and Evaluations

**Feature**: 007-quality-evals | **Date**: 2026-10-16

All tables carry `workspace_id` with row-level security. The exception is `evaluators` and
`evaluator_versions`, whose built-in rows have `workspace_id IS NULL`: the SELECT policy is
`workspace_id = current_setting('app.workspace_id') OR workspace_id IS NULL`, and INSERT, UPDATE
and DELETE policies allow only the current workspace (built-ins are written by a migration role).

IDs use the prefixes in architecture.md: `var_`, `evl_`, `evr_`, `ann_`. Child rows that are never
addressed by the API alone use bigint identity keys.

## analysis_variables (`var_`)

| Field | Type | Rules |
|---|---|---|
| id | text `var_...` | PK |
| workspace_id | text | RLS |
| agent_id | text `agt_` | FK agents |
| name | text | `^[a-z][a-z0-9_]{0,63}$`; unique per agent among `deleted_at IS NULL` |
| type | enum `boolean, string, number, choice` | |
| description | text | 1 to 500 chars, required |
| choices | text[] null | required for `choice`: 2 to 20 unique values, each 1 to 64 chars; null otherwise |
| position | integer | display and extraction order |
| deleted_at | timestamptz null | soft delete; stops future extraction |
| created_at, updated_at | timestamptz | |

Constraint: at most 25 rows per agent with `deleted_at IS NULL` (service check).

## call_analyses (1:1 with call)

| Field | Type | Rules |
|---|---|---|
| call_id | text `call_` | PK |
| workspace_id | text | RLS |
| status | enum `pending, running, completed, skipped, error` | |
| skip_reason / error | text null | `insufficient_credit`, provider message |
| model | text | model actually used |
| variable_snapshot | jsonb | `[{id, name, type, description, choices}]` used for this extraction |
| summary | text null | at most 600 chars (also written to `calls.summary` via 003) |
| sentiment | enum `positive, neutral, negative, unknown` null | |
| values | jsonb | `{name: value or null}`; values typed per variable; out-of-set choice stored as null |
| input_tokens, output_tokens | integer | |
| raw_cost_usd | numeric(12,6) | |
| charge_txn_id | text `txn_` null | |
| attempt | integer | increments on rerun |
| analyzed_at | timestamptz null | |

## evaluators (`evl_`)

| Field | Type | Rules |
|---|---|---|
| id | text `evl_...` | PK; built-ins get fixed IDs seeded by migration |
| workspace_id | text null | null for built-ins |
| kind | enum `builtin, custom` | |
| evaluator_type | text | built-in name, or `phrase_check`, `llm_judge_custom` |
| name | text | snake_case; built-ins globally unique; custom unique per workspace among non-deleted (409) |
| display_name | text | 1 to 80 chars |
| description | text null | at most 500 chars |
| scope | enum `call, turn, flow_node` | |
| cost_class | enum `free, llm_judge` | |
| agent_types | text[] | subset of `single_prompt, flow` |
| settings_schema | jsonb | `{fields:[{key, label, type: select, number, bool, text, text_long, options?, min?, max?, step?, default, helper?}]}` |
| score_range | jsonb | `{min, max}` |
| current_version | integer | >= 1 |
| enabled_by_default | boolean | true for free built-ins |
| deleted_at | timestamptz null | custom only, soft delete |
| created_at, updated_at | timestamptz | |

Constraint: at most 50 custom evaluators per workspace with `deleted_at IS NULL`.

## evaluator_versions

| Field | Type | Rules |
|---|---|---|
| evaluator_id | text `evl_` | PK part |
| version | integer | PK part; immutable row |
| workspace_id | text null | mirrors evaluator |
| definition | jsonb | custom: full config (phrase: `{pattern, mode, target, is_regex, case_sensitive}`; judge: `{question, pass_when, judge_model}`); built-in: `{judge_model, prompt_sha256, rules}` |
| judge_model | text null | |
| created_at | timestamptz | |
| created_by | text `usr_` null | |

## agent_eval_settings

| Field | Type | Rules |
|---|---|---|
| workspace_id | text | RLS |
| agent_id | text `agt_` | PK part |
| evaluator_id | text `evl_` | PK part |
| enabled | boolean | |
| overrides | jsonb | validated against `settings_schema` (types, min, max, options) |
| is_headline | boolean | at most 4 true per agent (service check plus partial unique index on position) |
| headline_position | smallint null | 1 to 4 |
| updated_by | text `usr_` | |
| updated_at | timestamptz | |

Absence of a row means: `enabled = enabled_by_default`, no overrides, not headline. Effective
settings = schema defaults overlaid with overrides.

## evaluator_runs (`evr_`)

| Field | Type | Rules |
|---|---|---|
| id | text `evr_...` | PK |
| workspace_id | text | RLS |
| call_id | text `call_` | |
| agent_id | text `agt_` | denormalised for queries |
| evaluator_id / evaluator_version | text / integer | FK evaluator_versions |
| run_group_id | text | groups the runs of one pipeline pass or rerun request |
| trigger | enum `pipeline, rerun, dataset, simulation` | `dataset` and `simulation` set by 008 |
| settings_snapshot | jsonb | effective settings used |
| settings_hash | text | sha256 of canonical JSON |
| status | enum `pending, running, completed, skipped, error` | |
| skip_reason | enum `insufficient_credit, not_applicable_agent_type, evaluator_disabled` null | |
| error | text null | |
| verdict | enum `pass, fail, not_applicable` null | set when completed |
| score | numeric null | mean of item scores |
| rationale | text null | non-empty when verdict is pass or fail |
| judge_model | text null | |
| input_tokens, output_tokens | integer | |
| raw_cost_usd | numeric(12,6) | |
| charge_txn_id | text `txn_` null | |
| attempt | smallint | 1 or 2 |
| created_at, started_at, completed_at | timestamptz | |
| superseded_at | timestamptz null | set on older runs when a newer group completes for the same call and evaluator |

Indexes: `(workspace_id, call_id) WHERE superseded_at IS NULL`; `(workspace_id, evaluator_id,
completed_at)`; `(workspace_id, agent_id, completed_at)`. Concurrency is guarded by
`evaluator_run_groups` below.

### evaluator_run_groups (guard)

`run_group_id` PK, `workspace_id`, `call_id`, `trigger`, `idempotency_key`, `status (active,
done)`, `created_at`. Partial unique index on `(call_id) WHERE status = 'active'` implements
"Checks are already running" (409).

## evaluator_result_items

| Field | Type | Rules |
|---|---|---|
| id | bigint identity | PK |
| workspace_id | text | RLS |
| run_id | text `evr_` | FK |
| turn_index | integer null | for `turn` scope |
| flow_node_id / flow_node_label | text null | for `flow_node` scope |
| verdict | enum `pass, fail, not_applicable` | |
| score | numeric null | |
| rationale | text | non-empty unless `not_applicable` |
| evidence | jsonb | `{turn_indices: [int], quote?: text}` |

Call-scope runs store exactly one item.

## annotations (`ann_`)

| Field | Type | Rules |
|---|---|---|
| id | text `ann_...` | PK |
| workspace_id | text | RLS |
| call_id | text `call_` | |
| user_id | text `usr_` | unique `(call_id, user_id)` |
| label | enum `good, bad` | |
| note | text null | at most 2,000 chars |
| created_at, updated_at | timestamptz | |

## Derived values (not stored)

### Run verdict (FR-015)

```
items_applicable = items where verdict != not_applicable
if no items_applicable: verdict = not_applicable, score = null
elif count(fail) > allowed_failures (setting max_failed_items, default 0): verdict = fail
else: verdict = pass
score = mean(score of items_applicable)
```

For threshold evaluators, item verdict = `pass` if `score >= pass_threshold` else `fail`.

### Call evaluation status (FR-016)

Over current runs (`superseded_at IS NULL`): none -> `not_evaluated`; any pending or running ->
`running`; any completed with verdict fail -> `failed`; any completed -> `passed`; otherwise (all
error or skipped) -> `error`.

### Calibration row

`{evaluator_id, evaluator_name, display_name, scope, cost_class, flow_node_id?, flow_node_label?,
version_scope (current, all), both_pass, both_fail, over_eager, missed, n, agreement_rate,
agreement_ci {low, high}, under_min_sample, reading (insufficient, strong, over_eager, misses,
partial, low), current_threshold?, best_threshold?, best_threshold_agreement?}`. Math in
research R7.

### Review queue item

`{call_id, agent_id, agent_name, ended_at, duration_s, sentiment, eval_count, pass_count,
fail_count}` over current completed runs with verdict pass or fail.

## State transitions

```
evaluator_runs.status:  pending -> running -> completed
                                           -> error  (after 1 retry)
                        pending -> skipped           (insufficient credit, not applicable to agent type)
call_analyses.status:   pending -> running -> completed | error ; pending -> skipped
evaluator_run_groups:   active -> done (when every run in the group is terminal)
evaluators (custom):    live -> deleted (soft; version rows kept)
```
