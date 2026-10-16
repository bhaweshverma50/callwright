# Phase 0 Research: Calls and Analytics

**Feature**: 006-calls-analytics | **Date**: 2026-10-16

Each entry records a decision, why it was made, and what else was considered. All
"NEEDS CLARIFICATION" items from the Technical Context are resolved here.

## R1. Dashboard and list queries: query live tables, no rollups

- **Decision**: Compute every dashboard figure with aggregate SQL over the `calls` table (owned by
  003) and `call_events` (turn latency), filtered by `workspace_id` and `started_at`. Add composite
  indexes `(workspace_id, started_at DESC)`, `(workspace_id, agent_id, started_at DESC)` and
  `(workspace_id, status, started_at DESC)` in this feature's migration. Daily buckets use
  `date_trunc('day', started_at AT TIME ZONE :tz)` and `generate_series` for zero-fill; ranges over
  180 days bucket by ISO week.
- **Rationale**: Principle VI. At the target scale (100,000 calls per 30-day window per workspace)
  an index range scan plus hash aggregate fits the 2 s budget. Rollups add a job, a backfill path
  and drift risk.
- **Alternatives considered**: nightly or streaming daily rollup tables (rejected until a measured
  p95 breach; the trigger is SC-002 failing in the load test, recorded in Complexity Tracking if
  added); a separate OLAP store (rejected: second datastore, violates Principle VI).

## R2. Turn latency percentiles

- **Decision**: Per-call latency stats (avg, p50, p95, measured turn count) are read from the
  call's stored latency summary (written by 003 at finalisation). The dashboard's median and p95
  turn latency use `percentile_cont` over `call_events.e2e_ms` for the window. Missing parts stay
  `null` and render "n/a".
- **Rationale**: Principle II requires measured values. The reference product substitutes 100 ms
  for a missing TTS figure; that hides regressions.
- **Alternatives considered**: averaging per-call medians (statistically wrong for fleet p95);
  t-digest sketches (unneeded at this scale).

## R3. Quality data seam between 006 and 007

- **Decision**: 006 defines `CallQualityPort` in `services/api/app/calls/quality_port.py` with
  three operations: per-call quality summary (eval status, pass and fail counts, viewer's label),
  list-filter clause for `label` and `eval_status`, and per-evaluator window stats for the
  dashboard. 006 ships a null implementation (everything `not_evaluated` / `unannotated`, empty
  stats). 007 registers the real implementation at app start.
- **Rationale**: 007 depends on 006 (architecture section 3), yet the call list, detail, compare
  and dashboard must show quality data. A port keeps the dependency direction and lets 006 ship
  first with correct empty states.
- **Alternatives considered**: denormalised quality columns on `calls` (cross-module writes into
  003's table); moving the quality dashboard into 007 (splits one page across two modules'
  contracts).

## R4. Analytics assistant: constrained query layer (no model-written SQL)

- **Decision**: The model never writes SQL. It may only call one tool, `run_metric_query`, whose
  argument is a typed `MetricQuery`:
  - `metrics`: 1 to 4 names from a fixed catalog (`call_count`, `total_duration_s`,
    `avg_duration_s`, `total_cost_usd`, `avg_cost_usd`, `median_turn_latency_ms`,
    `p95_turn_latency_ms`, `evaluator_pass_rate`, `evaluator_run_count`, `positive_sentiment_share`,
    `negative_sentiment_share`).
  - `group_by`: 0 to 2 names from a fixed catalog (`day`, `week`, `month`, `hour_of_day`,
    `weekday`, `agent`, `channel`, `status`, `disconnect_reason`, `sentiment`, `evaluator`).
  - `filters`: typed predicates on catalog dimensions only (`agent_ids`, `channels`, `statuses`,
    `disconnect_reasons`, `sentiments`, `evaluator_names`), values checked against enums or
    existing workspace agent IDs.
  - `period`: a preset (`today`, `yesterday`, `this_week`, `last_week`, `this_month`,
    `last_month`, `last_n_days` with n 1 to 365) or explicit dates, resolved server-side in the
    request timezone.
  - `order_by` (a metric or dimension in the query), `limit` 1 to 100.
  The server validates the argument with Pydantic, then a compiler in
  `services/api/app/analytics_chat/query_compiler.py` builds SQLAlchemy Core expressions against
  read-only views in a dedicated `analytics` schema (`analytics.calls_v`,
  `analytics.turn_latency_v`, `analytics.evaluator_verdicts_v`). Every value is a bound parameter.
- **Execution guard rails**:
  - the views are created `WITH (security_invoker = true)` so the underlying tables' RLS applies;
  - the query runs on a connection as role `cw_analytics_reader`, which has `USAGE` on schema
    `analytics` and `SELECT` on those views only, no table grants;
  - the transaction is `SET TRANSACTION READ ONLY` with `SET LOCAL app.workspace_id` and
    `SET LOCAL statement_timeout = '3s'`;
  - at most 3 tool calls per question, at most 100 rows returned to the model and the client;
  - the views expose no transcript text and no phone numbers (FR-027).
- **Rationale**: FR-024 forbids executing model-generated SQL. A typed query language closes
  injection, cross-tenant reads, writes and runaway queries by construction, and defence in depth
  (RLS, role grants, read-only transaction, timeout) covers compiler bugs. The fixed catalog also
  makes answers reproducible and lets the UI show "How this was computed" (FR-025).
- **Alternatives considered**: text-to-SQL with a SQL parser allowlist (parsers miss edge cases,
  and one miss is a tenant breach); canned questions only (too rigid for the stated use);
  shipping raw rows to the model (cost, privacy and wrong arithmetic).

## R5. Assistant model access and answer shape

- **Decision**: Use the provider-agnostic completion client exposed by the `llms` module (002) with
  tool calling and a JSON-schema final answer `{content, chart?, table?}`. Model id from setting
  `ANALYTICS_CHAT_MODEL` (default a small fast model in the catalog). Non-streaming request with a
  60 s budget. Numbers in the chart and table come from the query result, not from the model:
  the model selects which result set to chart and which keys to plot; the server copies the data.
- **Rationale**: Principle I (no vendor hard-coding). Copying data server-side prevents the model
  from inventing figures in charts.
- **Alternatives considered**: streaming tokens (more UI work, little value for short answers);
  letting the model emit chart data (hallucination risk).

## R6. Charging analytics questions

- **Decision**: Pre-check balance (> 0) before calling the model; on a successful answer call
  `billing.charge_feature(feature="analytics_chat", raw_cost_usd=<token cost from catalog>,
  idempotency_key=<Idempotency-Key header>)`. Declined questions (no query run) and failures are
  not charged. Each request is logged in `analytics_chat_requests` (internal, 30-day retention).
- **Rationale**: Principle III and architecture section 7 (all feature charges through
  `billing.charge_feature`). Charging after success avoids refunds.
- **Alternatives considered**: charging up front and refunding on failure (extra ledger rows).

## R7. Voice copilot transcription

- **Decision**: Browser-direct streaming STT with a short-lived, transcription-only credential
  minted by the API. API side: `services/api/app/voice_commands/stt/` holds one adapter per vendor
  with two methods, `mint_stream_credential(ttl_s)` and `transcribe(audio_bytes, mime)`; default
  vendor Deepgram (temporary key, TTL 60 s, scope listen only). The token response carries a
  vendor-neutral descriptor (`provider`, `stream_url`, `auth_scheme`, `token`, `expires_at`,
  `encoding`, `sample_rate_hz`) and the web app picks a matching client adapter in
  `apps/web/src/app/copilot/stt/<vendor>.ts`. Fallback: `POST /v1/voice-commands/transcribe` with
  the recorded clip (max 30 s, 2 MB). Rate limit 30 tokens per user per minute (Redis).
- **Rationale**: Lowest latency (no extra hop), no audio through our servers, vendor swappable
  (Principle I). TTL and scope limit the blast radius of a leaked credential.
- **Alternatives considered**: proxying audio through an API WebSocket (adds a hop and long-lived
  connections to the API); joining a LiveKit room for each command (heavy for a 3 s clip).

## R8. Voice command interpretation

- **Decision**: One model call with a JSON-schema output
  `{action, target, params, query, speak, highlight_element, fallback_suggestion}` given the
  transcript, `visual_state` (current route, page title, registered actions with parameter
  schemas, visible entities, open panels, current datetime and timezone) and the last 12
  exchanges. The server then validates: `navigate` targets must be in the route allowlist
  (`services/api/app/voice_commands/routes_allowlist.py`, mirrored from the web router);
  `ui_action` targets must be in `visual_state.available_actions` and params must validate against
  that action's schema; `route_to_copilot` targets must be `analytics_chat`, `prompt_builder` or
  `flow_builder`. Any failed check is rewritten to `decline` with a suggestion. Model from setting
  `VOICE_COMMAND_MODEL`; usage recorded as feature `voice_copilot`.
- **Rationale**: The model proposes; the server and the page decide. This blocks a spoken or
  transcribed prompt from triggering an unregistered action (FR-031).
- **Alternatives considered**: client-only intent rules (brittle); letting the model emit CSS
  selectors for clicks (unsafe and fragile; `highlight_element` is limited to a registered
  element key, not a selector).

## R9. Recording links

- **Decision**: `GET /v1/calls/{call_id}/recording` returns an S3 presigned GET URL with a 600 s
  expiry, plus a download variant with `Content-Disposition: attachment; filename=call_<id>.<ext>`.
  If the object is gone due to retention, return 410 with problem type `recording_deleted`; if
  egress is still finishing, 409 `recording_processing`. The web player refetches the link on a
  403 from storage.
- **Rationale**: Principle V and architecture section 7 (10-minute signed URLs).
- **Alternatives considered**: streaming through the API (bandwidth and cost on the API service).

## R10. Charts and tables in the web app

- **Decision**: Recharts for dashboard and assistant charts; `@tanstack/react-table` for the call
  list; `@tanstack/react-virtual` for transcripts over 500 items and long tables. URL state via
  React Router search params.
- **Rationale**: Recharts covers bar, line, area and pie with small effort; TanStack libraries match
  the TanStack Query choice in the constitution.
- **Alternatives considered**: hand-built SVG charts (time); a commercial grid (licence).

## R11. Origin of calls

- **Decision**: Read a call `origin` of `live | test | simulation` from the calls table. Default
  history and dashboard filter `origin = live` (dashboard) and `origin IN (live, test)` (history).
- **Rationale**: Simulated output calls must not inflate fleet KPIs or cost (FR-007, FR-022).
- **Note**: architecture.md section 5 does not list `origin` on Call. 003 must add it (write side)
  and 008 must set `simulation`. Raised as a conflict in the feature report.

## R12. Contract testing

- **Decision**: Contract tests load `specs/006-calls-analytics/contracts/*.yaml` with
  `openapi-core` and validate request and response of every operation against the running app
  (httpx `ASGITransport`) using seeded data.
- **Rationale**: Principle VII: drift fails CI.
