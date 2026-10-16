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
| name | text | `^[a-z][a-z0-9_]{0,63}$`; unique per agent among `deleted_at IS NULL`; the web form normalises typed text to this form (FR-045), the API never rewrites names |
| type | enum `boolean, string, number, choice` | |
| description | text | 1 to 500 chars, required |
| choices | text[] null | required for `choice`: 2 to 20 unique values, each 1 to 64 chars; must be null for `boolean`, `string`, `number` (422 if sent, FR-046) |
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
| scope | enum `call, turn, flow_node` | built-ins use `call` or `turn` only (catalog below); `flow_node` is reserved; per-node attribution lives on result items |
| cost_class | enum `free, llm_judge` | |
| output_kind | enum `class, anomaly, audio_quality, process_reward` | custom evaluators are `class` |
| agent_types | text[] | subset of `single_prompt, flow` |
| settings_schema | jsonb | `{fields:[{key, label, type: select, number, int, bool, text, text_long, options?, options_source?, min?, max?, step?, default, helper?}]}`; `int` renders as a stepper; `options_source: judge_models` fills `options` at read time from `EVAL_JUDGE_MODELS`; `helper` may contain `{default}`, replaced with the field default when served |
| score_range | jsonb | `{min, max}` |
| current_version | integer | >= 1 |
| enabled_by_default | boolean | true only for `flow_completion`, `audio_silence`, `node_dead_end`, `stuck_loop_detector`, `latency_slo` |
| deleted_at | timestamptz null | custom only, soft delete |
| created_at, updated_at | timestamptz | |

Constraint: at most 50 custom evaluators per workspace with `deleted_at IS NULL`.

### Built-in catalog (seeded by the registry sync, research R3)

Rows are listed in display order (alphabetical by display name). "Flow" in agent types means
`{flow}` only; "all" means `{single_prompt, flow}`. Display names and descriptions are our own.

| name | display_name | scope | cost_class | output_kind | agent types | default on | settings (key: type, min to max, default) |
|---|---|---|---|---|---|---|---|
| `anomaly_detection` | Anomaly detection | call | free | anomaly | all | no | `threshold`: number 0 to 1, 0.7; `window_days`: int 1 to 365, 30; `min_sample_size`: int 5 to 500, 30; `knn_k`: int 1 to 50, 10; `backfill_per_run`: int 0 to 20, 5 |
| `factual_consistency` | Factual consistency | call | llm_judge | class | all | no | `judge_model`: select (judge models), platform default |
| `flow_completion` | Flow completion | call | free | class | flow | yes | none |
| `intent_fulfillment` | Intent fulfillment | call | llm_judge | class | all | no | `judge_model`: select, platform default; `sample_rate_pct`: int 1 to 100, 100 |
| `kb_relevance` | Knowledge retrieval relevance | call | llm_judge | class | all | no | `judge_model`: select, platform default |
| `audio_silence` | Long silences | call | free | audio_quality | all | yes | `max_acceptable_silence_ms`: int 500 to 60000, 3000; `silence_threshold_db`: number -80 to -10, -40; `min_silence_ms`: int 200 to 10000, 1000 |
| `node_dead_end` | Node dead ends | call | free | class | flow | yes | none |
| `process_reward` | Per-turn progress | turn | llm_judge | process_reward | all | no | `judge_model`: select, platform default |
| `stuck_loop_detector` | Stuck loops | call | free | class | flow | yes | `max_visits_per_node`: int 2 to 10, 3 |
| `tool_call_correctness` | Tool call correctness | call | llm_judge | class | all | no | `judge_model`: select, platform default |
| `transition_correctness` | Transition correctness | call | llm_judge | class | flow | no | `judge_model`: select, platform default |
| `latency_slo` | Turn latency | turn | free | class | all | yes | `threshold_ms`: int 100 to 30000, 3000 |

Settings validation (FR-038): `int` rejects non-integers; `number` accepts decimals; both reject
values outside `[min, max]` with `{field, message}` errors (422). `select` rejects values not in
`options`. Unknown keys are rejected. A stored override that falls outside a newer version's range
is clamped when computing effective settings, and the response marks it `adjusted`.

## call_embeddings (anomaly detection, FR-042)

| Field | Type | Rules |
|---|---|---|
| call_id | text `call_` | PK |
| workspace_id | text | RLS |
| agent_id | text `agt_` | |
| ended_at | timestamptz | copied from the call for window filtering |
| embedding | vector(n) | n = 005's embedding dimension; cosine distance |
| model | text | embedding model id |
| source_sha256 | text | hash of the text that was embedded |
| created_at | timestamptz | |

Index: HNSW `(embedding vector_cosine_ops)`; btree `(workspace_id, agent_id, ended_at)`. Rows are
deleted with the call by retention. Only calls of origin `live` are embedded.

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
settings = schema defaults overlaid with overrides. Every write (switch toggle or "Save settings")
is a full PUT of `{enabled, overrides, is_headline}` that replaces the row (FR-039); there is no
partial update.

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
| skip_reason | enum `insufficient_credit, not_applicable_agent_type, evaluator_disabled, not_sampled` null | `not_sampled` only for trigger `pipeline` on live calls (FR-037); never charged |
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
| turn_index | integer null | for `turn` scope and for `latency_slo` failing turns |
| flow_node_id / flow_node_label | text null | set by `node_dead_end` (one item per visited node), `stuck_loop_detector` (one item per node over the limit) and `transition_correctness` (source node of each judged transition) |
| start_ms / duration_ms | integer null | `audio_silence`: start offset and length of each reported silence |
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

Item verdicts per built-in (research R3):
- judges (`class`): `pass` if `score >= 0.5` (cutoff pinned in the evaluator version, not a setting);
- `process_reward`: item fails at -1;
- `anomaly_detection`: one item, score = mean cosine distance, `fail` if score > `threshold`,
  `not_applicable` (rationale "insufficient data") if neighbours < `min_sample_size`;
- `audio_silence`: one item, score = longest silence in ms, `fail` if > `max_acceptable_silence_ms`;
- `latency_slo`: one item per agent turn, score = e2e ms, `fail` if > `threshold_ms`;
- `stuck_loop_detector`: one item per visited node, `fail` if visits > `max_visits_per_node`;
- `flow_completion`: one item, `pass` if the last node is `end` or `transfer`;
- `node_dead_end`: one item per visited node, `fail` if the call ended on it and it is not `end`
  or `transfer`.

Sampling (FR-037): `selected = int(sha256(call_id + ":" + evaluator_name)[:8], 16) % 100 <
sample_rate_pct`; applied only when `trigger = pipeline` and the call origin is `live`.

### Call evaluation status (FR-016)

Over current runs (`superseded_at IS NULL`): none -> `not_evaluated`; any pending or running ->
`running`; any completed with verdict fail -> `failed`; any completed -> `passed`; otherwise (all
error or skipped) -> `error`.

### Calibration row

Rows split by node for evaluators whose items carry `flow_node_id`. Fields:
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
