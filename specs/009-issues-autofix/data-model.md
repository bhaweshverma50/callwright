# Data Model: Issues and Auto-Fix

**Feature**: 009-issues-autofix | **Date**: 2026-10-16

All tables carry `workspace_id` with row-level security on `app.workspace_id`. Public IDs use
the `iss_` prefix only; revisions and attempts are integers scoped to an issue.

## Enums

| Enum | Values |
|---|---|
| `issue_status` | `open`, `validating`, `validated`, `applied`, `dismissed` |
| `issue_origin` | `real`, `simulated`, `mixed` (simulated when at least 80% of samples are simulated, real when at most 20%) |
| `fix_kind` | `prompt_edit`, `node_prompt_edit`, `add_guardrail`, `tool_description_edit`, `transition_condition_edit`, `add_transition`, `node_tool_attachment`, `kb_attach` |
| `fix_source` | `ai`, `manual` |
| `fix_status` | `draft`, `validating`, `passed`, `failed`, `inconclusive`, `superseded`, `applied`, `advisory` |
| `validation_status` | `running`, `completed`, `cancelled`, `error` |
| `validation_decision` | `passed`, `failed`, `inconclusive` |
| `dismiss_reason` | `not_a_problem`, `evaluator_wrong`, `wont_fix`, `duplicate`, `other` |
| `detection_status` | `running`, `completed`, `failed` |

## issues (`iss_`)

| Field | Type | Rules |
|---|---|---|
| id | text | `iss_` ULID |
| workspace_id, agent_id | text | |
| agent_type | text | `single_prompt` or `flow`, copied at creation |
| title | text | 1-80 chars |
| description | text | up to 1,000 chars |
| suspected_cause | text null | from naming step |
| evaluator_id | text | `evl_` |
| evaluator_name | text | |
| evaluator_version | int | version of the newest sample's verdict |
| flow_node_id, flow_node_label | text null | |
| status | issue_status | |
| origin | issue_origin | |
| affected_call_count | int | distinct calls matched across detections in the latest window |
| current_version_call_count | int | affected calls that ran on the published version at detection time |
| first_seen_at, last_seen_at | timestamptz | |
| centroid | vector(N) | N = embedding dimension of 005's model |
| window_days | int | of the detection that last updated it |
| current_fix_revision | int null | |
| calibration_warning | bool | set from 007 calibration at detection time |
| recurrence_of | text null | `iss_` of an applied issue |
| applied_agent_version_id | text null | `agv_` |
| applied_at | timestamptz null | |
| applied_by | text null | `usr_` |
| dismiss_reason | dismiss_reason null | |
| dismiss_note | text null | required when reason `other`; up to 500 chars |
| duplicate_of | text null | required when reason `duplicate`; must be another issue of the same agent |
| dismissed_at, dismissed_by | | |
| created_at, updated_at | timestamptz | |

List filters (FR-026): index `(workspace_id, agent_id, last_seen_at desc)`; `window_days` on the
list keeps `last_seen_at >= now() - window_days`; `scope = real` excludes `issue_origin =
simulated` (mostly simulated samples).

### State transitions

```
open ---------(validate / draft-and-validate)---------> validating
validating ---(decision passed)-----------------------> validated
validating ---(failed | inconclusive | cancel | error)-> open
validated ----(new revision becomes current)----------> open
validated ----(re-validate)---------------------------> validating
validated ----(apply)---------------------------------> applied     [final]
open | validating | validated ---(dismiss)-----------> dismissed   [final]
```

Guards: `validate` needs a current revision whose status is `draft`, `failed`, `inconclusive`
or `passed` (re-validate) and not `advisory`; `apply` needs the preconditions in research R5.

## issue_samples (PK `issue_id`, `call_id`)

| Field | Type | Rules |
|---|---|---|
| issue_id, call_id | text | `call_id` FK calls on delete cascade (retention) |
| workspace_id | text | |
| evaluator_result_ids | text[] | the failing results (one, or several turns) |
| reason_excerpt | text | up to 500 chars |
| agent_version_id | text | version the call ran on |
| call_origin | text | `live` or `simulation` |
| base_call_id | text null | for simulated samples, the simulation run's base call |
| failed_at | timestamptz | call end time |

At most 50 kept per issue, most recent first; counts on `issues` are kept separately.

## issue_failure_embeddings (PK `evaluator_result_id`)

| Field | Type | Rules |
|---|---|---|
| evaluator_result_id | text | |
| workspace_id | text | |
| embedding_model | text | cache key part; re-embed when the model changes |
| embedding | vector(N) | |
| created_at | timestamptz | purged with the call |

## issue_fixes (PK `issue_id`, `revision`)

| Field | Type | Rules |
|---|---|---|
| issue_id | text | |
| revision | int | starts at 1, increments per issue |
| workspace_id | text | |
| kind | fix_kind | must be allowed for the issue (spec FR-008) |
| payload | jsonb | per-kind schema below |
| rationale | text | |
| source | fix_source | |
| guidance | text null | user guidance given to the drafter |
| base_agent_version_id | text | published version when drafted |
| base_config_hash | text | |
| variant_config_hash | text null | null for advisory fixes |
| variant_snapshot | jsonb null | full snapshot with the fix applied |
| diff | jsonb | `[{op, path, value, old}]` for display |
| status | fix_status | |
| created_at, created_by | | |

### Payload schemas by kind

| kind | payload |
|---|---|
| `prompt_edit` | `{current_prompt, proposed_prompt}` |
| `node_prompt_edit` | `{node_id, node_label, current_instructions, proposed_instructions}` |
| `add_guardrail` | `{placement: agent_prompt or node or all_agent_nodes, node_id?, rule_text}` (rule_text 1-500 chars) |
| `tool_description_edit` | `{tool_id, tool_name, current_description, proposed_description}` |
| `transition_condition_edit` | `{edge_id, edge_label, source_node_id, current_condition, proposed_condition}` |
| `add_transition` | `{source_node_id, target_node_id, edge_label, handoff_condition}` |
| `node_tool_attachment` | `{node_id, tools_to_attach[], tools_to_detach[]}` (one list non-empty) |
| `kb_attach` | `{kb_ids_to_attach[], uncovered_topics[]}` (advisory when kb_ids_to_attach is empty) |

When a new revision is stored, the previous current revision becomes `superseded` unless it is
`failed`, `inconclusive` or `applied` (those keep their status as history).

## issue_validations (PK `issue_id`, `attempt`)

Immutable after `status` leaves `running` (enforced by a trigger that rejects updates of
completed rows).

| Field | Type | Rules |
|---|---|---|
| issue_id | text | |
| attempt | int | starts at 1 |
| workspace_id | text | |
| fix_revision | int | |
| auto | bool | true when started by draft-and-validate |
| mode | text | `persona` (default) or `replay` |
| min_improvement_pp | numeric(5,2) | 5-50, default 10 |
| max_regression_pp | numeric(5,2) | 0-20, default 5 |
| min_sample | int | 3-50, default 5 |
| base_agent_version_id | text | |
| base_config_hash, variant_config_hash | text | |
| affected_call_ids | text[] | up to 20 |
| guard_call_ids | text[] | up to 10 |
| control_experiment_id, treatment_experiment_id | text | `exp_` |
| status | validation_status | |
| decision | validation_decision null | |
| reasons | jsonb | `[{code, evaluator_id?, set?, delta_pp?, n?}]` |
| headline | jsonb null | `{evaluator_id, n, control_passes, treatment_passes, control_rate, treatment_rate, delta_pp}` |
| evaluator_results | jsonb | `[{evaluator_id, evaluator_name, evaluator_version, set: affected or guard or combined, n, control_passes, treatment_passes, delta_pp, blocking, insufficient_data, version_mismatch}]` |
| treatment_runs_total, treatment_runs_failed | int | |
| estimated_cost_usd, cost_usd | numeric(12,6) | |
| started_at, finished_at | timestamptz | |

## issue_detection_runs (internal UUID PK, not exposed)

| Field | Type | Rules |
|---|---|---|
| id | uuid | |
| workspace_id, agent_id | text | partial unique index on `(agent_id)` where `status = 'running'` |
| window_days | int | 7, 14, 30 or 90 |
| include_simulated | bool | |
| status | detection_status | |
| calls_scanned, failures_scanned, issues_created, issues_updated | int | |
| cost_usd | numeric(12,6) | |
| error_message | text null | |
| started_at, finished_at | timestamptz | |

## Computed: post-apply tracking (not stored)

`{before: {agent_version_id, n, passes, rate}, after: {agent_version_id, n, passes, rate},
delta_pp, ready: after.n >= 10}` for the headline evaluator on live calls (research R8).
