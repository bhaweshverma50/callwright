# Data Model: Calls and Analytics

**Feature**: 006-calls-analytics | **Date**: 2026-10-16

This feature is mostly a read side. It owns two small tables, a set of read-only views and new
indexes, and consumes tables written by 001, 003 and 007. All tenant tables carry `workspace_id`
with row-level security (`workspace_id = current_setting('app.workspace_id')`).

## 1. Consumed records (owned elsewhere)

Field names below are the names this feature reads. If the owning plan names them differently,
the owning plan wins and this document is updated.

### Call (`calls`, owner 003 write side)

| Field | Type | Notes |
|---|---|---|
| id | text `call_...` | PK |
| workspace_id | text `ws_...` | RLS |
| agent_id / agent_version_id | text `agt_` / `agv_` | version the call ran |
| agent_name_snapshot | text | name at call time; shown when the agent is deleted |
| channel | enum `web, sip_inbound, sip_outbound, whatsapp` | architecture section 5 |
| origin | enum `live, test, simulation` | **required addition, see research R11** |
| from_number / to_number | text null | E.164 or null for web |
| status | enum `queued, ringing, in_progress, ended, processing, completed, failed, no_answer, busy, voicemail` | lifecycle |
| disconnect_reason | enum `user_hangup, agent_hangup, call_transfer, voicemail_reached, inactivity, max_duration_reached, error, concurrency_limit, insufficient_credit` null | |
| started_at / ended_at | timestamptz | |
| duration_s | integer | whole seconds, rounded up (001) |
| recording_key | text null | object key; never returned |
| transcript | jsonb | ordered items, see section 3 |
| summary | text null | written by 007 |
| sentiment | enum `positive, neutral, negative, unknown` null | written by 007 |
| analysis_values | jsonb null | `{variable_name: value}` written by 007 |
| cost_total_usd | numeric(12,6) null | from 001 pricing |
| latency_avg_ms / latency_p50_ms / latency_p95_ms | integer null | per-call summary (003) |
| latency_turns_measured | integer | |

### CallEvent (`call_events`, owner 003)

| Field | Type | Notes |
|---|---|---|
| call_id, workspace_id | text | |
| kind | enum `turn_metrics, tool_call, flow_transition, usage` | |
| turn_index | integer | agent turn ordinal, 0-based |
| stt_final_ms, llm_ttft_ms, tts_ttfb_ms, e2e_ms | integer null | `turn_metrics` |
| from_node_id, from_node_label, to_node_id, to_node_label, transition_label | text | `flow_transition` |
| occurred_at | timestamptz | ordering |

### Cost lines (`call_cost_lines`, owner 001)

`component` (`stt, llm, tts, nc, platform`), `provider`, `model`, `rate_per_min_usd`,
`billed_minutes`, `cost_usd`, `surcharge_usd`, `bundle_multiplier`, `catalog_version`.

### Quality data (owner 007, via `CallQualityPort`)

Per call: `eval_status` (`not_evaluated, running, passed, failed, error`), `pass_count`,
`fail_count`, viewer's `label` (`good, bad`, or null meaning unannotated). Per evaluator and window:
pass, fail and not-applicable counts, average score, calls evaluated, headline flag.

## 2. Owned tables

### `analytics_chat_requests` (audit log, internal)

| Field | Type | Rules |
|---|---|---|
| id | bigint identity | internal only, never exposed (no public ID prefix needed) |
| workspace_id | text | RLS |
| user_id | text `usr_` | |
| idempotency_key | text | unique per workspace; replay returns stored response |
| question | text | last user message, max 2,000 chars |
| metric_queries | jsonb | validated `MetricQuery` list actually executed |
| outcome | enum `answered, declined, failed, refused_balance` | |
| response | jsonb | stored answer for idempotent replay |
| input_tokens / output_tokens | integer | |
| raw_cost_usd | numeric(12,6) | |
| charge_txn_id | text `txn_` null | set when charged |
| latency_ms | integer | |
| created_at | timestamptz | rows older than 30 days purged by a daily job |

### `voice_command_logs` (audit log, internal)

| Field | Type | Rules |
|---|---|---|
| id | bigint identity | internal |
| workspace_id, user_id | text | RLS |
| route | text | page the command was spoken on |
| transcript | text | max 1,000 chars |
| action | enum `navigate, route_to_copilot, ui_action, answer, decline` | final, after validation |
| downgraded | boolean | true when server validation turned the model output into `decline` |
| stt_seconds | numeric(8,2) | for usage |
| raw_cost_usd | numeric(12,6) | |
| created_at | timestamptz | purged after 30 days |

### Indexes added on `calls`

- `(workspace_id, started_at DESC)`
- `(workspace_id, agent_id, started_at DESC)`
- `(workspace_id, status, started_at DESC)`
- `(workspace_id, origin, started_at DESC)`
- `(workspace_id, duration_s)`, `(workspace_id, cost_total_usd)`, `(workspace_id, latency_avg_ms)` for sort
- `call_events (workspace_id, kind, occurred_at)` for window latency percentiles
- Expression indexes `(workspace_id, regexp_replace(from_number, '\D', '', 'g') text_pattern_ops)`
  and the same for `to_number`, for prefix search on digits (CallListQuery).

### Views in schema `analytics` (read by the assistant only)

All `WITH (security_invoker = true)`; role `cw_analytics_reader` has `SELECT` on these only.

- `analytics.calls_v`: `call_id, workspace_id, agent_id, agent_name, channel, status,
  disconnect_reason, sentiment, started_at, duration_s, cost_usd` where `origin = 'live'`.
  No numbers, no transcript, no summary.
- `analytics.turn_latency_v`: `workspace_id, call_id, agent_id, occurred_at, e2e_ms`.
- `analytics.evaluator_verdicts_v`: `workspace_id, call_id, agent_id, evaluator_name, verdict,
  score, started_at` (current run per call and evaluator). Created by 006 as an empty-returning
  stub; 007's migration replaces it with the real definition.

## 3. Read models (API shapes)

### TranscriptItem (discriminated by `type`)

| type | fields |
|---|---|
| `message` | `id, role (user, agent), text, interrupted, stt_confidence (0 to 1, user only), offset_ms, turn_index (agent only)` |
| `tool_call` | `id, tool_name, arguments (object), offset_ms, turn_index` |
| `tool_result` | `id, tool_call_id, tool_name, output (string), is_error, duration_ms, offset_ms` |

Plain-text copy format: `Agent: ...`, `Caller: ...`, `[Tool call: name({json})]`,
`[Tool result: name -> output]`, `[Tool error: name -> output]`.

### CallListItem

`call_id, started_at, agent {id, name, deleted}, from_number, to_number, channel, origin,
disconnect_reason, duration_s, status, cost_usd, latency_avg_ms, has_recording, summary,
sentiment, analysis_values, quality {eval_status, pass_count, fail_count, label}`.

### CallDetail

CallListItem plus `agent_version_id, agent_version_label, ended_at, latency {avg_ms, p50_ms,
p95_ms, turns_measured}, cost {header {duration_s, billed_minutes, avg_rate_per_min_usd,
total_usd}, lines[], surcharges[]}, processing_state (pending, done)`.

- `lines[]`: `{component, provider, model, rate_per_min_usd, billed_minutes, cost_usd}`; `nc`
  omitted when zero.
- `surcharges[]`: `{component (llm, tts), label, surcharge_usd, multiplier}` only when
  `surcharge_usd > 0`.
- `avg_rate_per_min_usd = total_usd / (duration_s / 60)`.

### TurnLatency

`{turn_index, stt_final_ms, llm_ttft_ms, tts_ttfb_ms, e2e_ms}`; any part may be null.

### FlowTransition

`{sequence, from_node_id, from_node_label, to_node_id, to_node_label, transition_label,
occurred_offset_ms}`.

### CallComparison

`{left: CallDetail, right: CallDetail, right_kind (call, simulation), alignment [{turn_index,
left_item_ids[], right_item_ids[]}], flow_diff [{sequence, left_node_id, right_node_id, differs}],
verdict_diffs [{evaluator_id, evaluator_name, left {verdict, score}, right {verdict, score},
score_delta, right_rationale}]}`. `verdict_diffs` is empty until 007 is registered.

### CallListQuery (request)

Sort and filters from `GET /v1/calls` (also used by `/v1/calls/export`). Date filters:
`start_date` and `end_date` are calendar dates resolved in `tz` to `[start 00:00, end + 1 day
00:00)` in UTC by the server; `started_after` and `started_before` remain for API clients and
are combined with AND when both forms are given. Phone filters: the server strips everything but
digits from `from_number` and `to_number` and matches `regexp_replace(number, '\D', '', 'g') LIKE
:digits || '%'`, backed by expression indexes on the digit form (section 2, indexes on `calls`).
The web client builds query strings with `URLSearchParams`, so `+` arrives as `%2B`. Export
streams CSV rows with the same query, capped at 10,000 rows (`export_too_large` above that).

### DashboardPeriod (request)

`period` (`all_time, last_7_days, last_30_days, last_90_days, custom`; default `last_30_days`),
`start_date`, `end_date` (inclusive, required for custom, end >= start, range <= 731 days),
`agent_ids[]`, `tz` (IANA name, default `UTC`). Resolved window is `[from, to)` in UTC.

### DashboardStats

`window {from, to, bucket (day, week)}, kpis {total_calls, daily_avg_calls, total_duration_s,
peak_day {date, total_calls}, total_cost_usd, cost_per_call_usd, avg_duration_s,
median_turn_latency_ms, p95_turn_latency_ms}, sparklines {calls[], duration_s[], cost_usd[],
avg_duration_s[]}, series [{bucket_start, total_calls, total_duration_s, avg_duration_s}],
disconnect_reasons {reason: count}, sentiment {positive, neutral, negative, unknown}, channels
{web, sip_inbound, sip_outbound, whatsapp}, leaderboard [{agent_id, agent_name, total_calls,
positive_calls, negative_calls}] (5), distribution [{agent_id or "others", agent_name,
total_calls, share}] (10 plus others)`.

Rules: `daily_avg_calls = total_calls / days_in_window` (all-time window starts at the first
call's day); cost and duration count only `ended`, `processing` and `completed` calls of origin
`live`.

### DashboardQuality

`window, prior_window, total_calls_evaluated, per_evaluator [{evaluator_id, evaluator_name,
display_name, scope, pass_rate (null when pass + fail = 0), avg_score, pass_count, fail_count,
not_applicable_count, total_runs, calls_evaluated}], per_evaluator_prior [same]`.

### AgentHealth

`window (last 30 days), prior_window (30 days before), items [{evaluator_id, display_name,
pass_rate, prior_pass_rate, delta_pp}]` limited to headline evaluators of the selected agents,
at most 4, ordered by run count. `delta_pp = round((pass_rate - prior_pass_rate) * 100, 1)`, null
if either side is null.

### MetricQuery and ChatAnswer

See research R4 for the catalog. `ChatAnswer = {content, chart?: {chart_type (bar, line, area,
pie), x_key, series [{key, label}], data [object]}, table?: {columns [{key, label, type}], rows
[object]}, truncated, computed_with [MetricQuery], outcome (answered, declined)}`.

### StreamCredential

`{provider, stream_url, auth_scheme, token, expires_at, encoding, sample_rate_hz, language}`.

### InterpretResult

`{action (navigate, route_to_copilot, ui_action, answer, decline), target, params, query,
speak, highlight_element, fallback_suggestion}`. `highlight_element` is a key registered by the
page, never a CSS selector.

## 4. State

No new lifecycles. `processing_state` on CallDetail is derived: `pending` while call status is
`ended` or `processing`, `done` otherwise.
