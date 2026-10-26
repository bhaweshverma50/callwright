---
description: "Task list for 006 Calls and Analytics"
---

# Tasks: Calls and Analytics

**Input**: Design documents from `specs/006-calls-analytics/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md
**Depends on**: 001 (billing, pricing, cost lines), 003 (calls write side, call_events), 002 (`llms` client)

**Tests**: Required by Principle VII. Contract tests for every module; cost view math, dashboard
aggregation, period resolution and the MetricQuery compiler are written first and must fail before
implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US6 from spec.md

---

## Phase 1: Setup

- [x] T001 Add web dependencies `recharts`, `@tanstack/react-table`, `@tanstack/react-virtual` in apps/web/package.json (react-table not needed: the list reuses the design-system table markup)
- [x] T002 [P] Add API dependency `openapi-core` (test extra) in services/api/pyproject.toml
- [x] T003 [P] Add settings `ANALYTICS_CHAT_MODEL`, `VOICE_COMMAND_MODEL`, `COPILOT_STT_PROVIDER`, `RECORDING_URL_TTL_S=600` in services/api/app/core/config.py
- [x] T004 Create migration (`s006_0001_calls_analytics.py`) with call indexes, `analytics_chat_requests`, `voice_command_logs`, schema `analytics`, role `cw_analytics_reader`, views `analytics.calls_v`, `analytics.turn_latency_v`, stub `analytics.evaluator_verdicts_v` (all `security_invoker`) in services/api/app/migrations/versions/0601_calls_analytics.py
- [x] T005 [P] Register routers for calls (read), recordings, dashboard, analytics_chat, voice_commands in services/api/app/main.py

---

## Phase 2: Foundational (blocks all stories)

- [x] T006 Define `CallQualityPort` protocol (per-call summary, list filter clause, window evaluator stats, verdicts for two calls) and `NullCallQualityPort` in services/api/app/calls/quality_port.py
- [x] T007 [P] Shared enums (Channel, Origin, CallStatus, DisconnectReason, Sentiment, EvalStatus) and Problem helpers in services/api/app/calls/schemas.py
- [x] T008 [P] Seed script for quickstart data (2 workspaces, 45 live + 2 simulation calls, reference call) in services/api/scripts/seed_006.py (built as `app/dev/seed_calls.py`)
- [x] T009 [P] Contract test harness loading `specs/006-calls-analytics/contracts/*.yaml` with openapi-core in services/api/tests/contract/conftest.py
- [x] T010 [P] RLS integration fixture creating two workspaces and asserting cross-tenant reads return nothing in services/api/tests/integration/conftest.py
- [x] T011 Regenerate the TS client from contracts in apps/web/src/api/ (script `pnpm --filter web gen:api`)

**Checkpoint**: migrations apply, routers mount, harnesses run (empty).

---

## Phase 3: User Story 1 - Find any call in the history (P1) MVP

**Goal**: list, sort, filter, paginate, select across pages, hand off to simulation.
**Independent Test**: quickstart section 2.

### Tests (write first, must fail)

- [x] T012 [P] [US1] Contract test for `GET /v1/calls` in services/api/tests/contract/test_calls_contract.py
- [x] T013 [P] [US1] Unit tests for filter parsing (comma lists, unknown values dropped, OR within, AND across), sort whitelist and page math in services/api/tests/unit/calls/test_list_query.py
- [x] T014 [P] [US1] Integration test: 45 seeded calls, default order, 20/20/5 pages, origin default hides simulation, ws_B sees none in services/api/tests/integration/test_calls_read.py

### Implementation

- [x] T015 [US1] Implement list query builder (filters, sort, pagination, quality port filter clause) in services/api/app/calls/queries.py
- [x] T016 [US1] Implement `GET /v1/calls` with CallPage response in services/api/app/calls/router.py
- [x] T017 [P] [US1] Call History page with URL-synced sort, filters and page in apps/web/src/routes/calls/CallHistoryPage.tsx
- [x] T018 [P] [US1] Filter bar with chips and "Clear all" in apps/web/src/routes/calls/CallFilters.tsx
- [x] T019 [P] [US1] Column definitions (all FR-002 columns, cost hover popover, inline recording player, quality cell) in apps/web/src/routes/calls/columns.tsx
- [x] T020 [P] [US1] Cross-page selection store (max 200, single-agent check, "Run simulation" hand-off to 008 route) in apps/web/src/routes/calls/selection.ts
- [x] T021 [US1] Web tests for filters, chips, selection persistence and mixed-agent block in apps/web/src/routes/calls/CallHistoryPage.test.tsx
- [x] T088 [P] [US1] Unit tests for phone filters (digits only, plus optional, prefix match, `%2B` round trip) and date filters (`start_date`, `end_date`, `tz`; Asia/Kolkata 2026-10-01 includes a call at 2026-09-30T20:00Z; inclusive end) in services/api/tests/unit/calls/test_list_query.py
- [x] T089 [US1] Implement date and timezone filters and digit-prefix phone filters in services/api/app/calls/queries.py, with the expression indexes on `from_number` and `to_number` added to the 006 migration (makes T088 pass)
- [x] T090 [P] [US1] Contract and integration tests for `GET /v1/calls/export` (same rows and order as the list, chosen columns, no transcript text, 422 `export_too_large` above 10,000 rows) in services/api/tests/contract/test_calls_contract.py and services/api/tests/integration/test_calls_export.py
- [x] T091 [US1] Implement streamed CSV export in services/api/app/calls/export.py and the endpoint in services/api/app/calls/router.py (makes T090 pass)
- [x] T092 [P] [US1] Call History web changes: rows per page 10/20/50/100, column visibility menu kept in browser storage (call ID, start time, status fixed), Export button, a chip for every applied filter including own label with the badge equal to the chip count and "Any" not counted, query strings built with `URLSearchParams`, dates sent as dates plus `tz`; in apps/web/src/routes/calls/CallHistoryPage.tsx, apps/web/src/routes/calls/CallFilters.tsx and apps/web/src/routes/calls/columns.tsx, with cases added to apps/web/src/routes/calls/CallHistoryPage.test.tsx

**Checkpoint**: US1 independently usable.

---

## Phase 4: User Story 2 - Understand one call (P1)

**Goal**: call detail drawer with transcript, recording, latency, flow path, analysis, cost.
**Independent Test**: quickstart section 3.

### Tests (write first, must fail)

- [x] T022 [P] [US2] Contract tests for `GET /v1/calls/{id}`, `/transcript`, `/turn-latencies`, `/flow-transitions` in services/api/tests/contract/test_calls_contract.py
- [x] T023 [P] [US2] Contract test for `GET /v1/calls/{id}/recording` (200, 404, 409, 410) in services/api/tests/contract/test_recordings_contract.py
- [x] T024 [P] [US2] Unit tests for cost view (reference call: header 271 s, 4.52 billed min, $0.106/m avg; LLM surcharge multiplier 1.13; nc omitted when zero; no surcharge lines when zero) in services/api/tests/unit/calls/test_cost_view.py
- [x] T025 [P] [US2] Unit tests for plain-text transcript format (tool call, tool result, tool error lines) in services/api/tests/unit/calls/test_transcript_text.py
- [x] T026 [P] [US2] Unit tests for recording service (TTL <= 600 s, attachment filename, retention 410, processing 409) in services/api/tests/unit/recordings/test_service.py

### Implementation

- [x] T027 [P] [US2] Cost view mapper from 001 cost lines in services/api/app/calls/cost_view.py
- [x] T028 [P] [US2] Transcript text formatter in services/api/app/calls/transcript_text.py
- [x] T029 [US2] Detail, transcript, turn-latency and flow-transition loaders in services/api/app/calls/queries.py
- [x] T030 [US2] Detail endpoints in services/api/app/calls/router.py
- [x] T031 [P] [US2] Presign service with retention and processing checks in services/api/app/recordings/service.py
- [x] T032 [US2] Recording endpoint in services/api/app/recordings/router.py
- [x] T033 [P] [US2] Call detail drawer at `/calls?call=` (header, processing state polling) in apps/web/src/routes/calls/CallDetailDrawer.tsx
- [x] T034 [P] [US2] Transcript view with tool items, interrupted chip, confidence, latency chips with "n/a" parts, virtualised over 500 items, copy button in apps/web/src/routes/calls/Transcript.tsx
- [x] T035 [P] [US2] Recording player with auto-refresh of expired links and download in apps/web/src/routes/calls/RecordingPlayer.tsx
- [x] T036 [P] [US2] Cost breakdown popover and panel in apps/web/src/routes/calls/CostBreakdown.tsx
- [x] T037 [P] [US2] Flow path list and analysis field/value table in apps/web/src/routes/calls/FlowPath.tsx and apps/web/src/routes/calls/AnalysisTable.tsx
- [x] T038 [US2] Web tests for drawer states (deleted recording, processing, single-prompt hides flow path) in apps/web/src/routes/calls/CallDetailDrawer.test.tsx

**Checkpoint**: US1 + US2 form the MVP.

---

## Phase 5: User Story 3 - Fleet dashboard (P2)

**Goal**: KPIs, series, breakdowns, quality grid, agent health.
**Independent Test**: quickstart section 4.

### Tests (write first, must fail)

- [x] T039 [P] [US3] Contract tests for `/v1/dashboard/stats`, `/quality`, `/agent-health` in services/api/tests/contract/test_dashboard_contract.py
- [x] T040 [P] [US3] Unit tests for period resolution (presets, custom inclusive end, end before start rejected, 731-day cap, Asia/Kolkata day boundary, all-time start at first call) in services/api/tests/unit/dashboard/test_periods.py
- [x] T041 [P] [US3] Unit tests for aggregation helpers (zero-fill, weekly bucket over 180 days, daily average 10/7 = 1.43, top 10 + Others, pass rate excludes not-applicable, delta_pp rounding and nulls) in services/api/tests/unit/dashboard/test_aggregates.py
- [x] T042 [P] [US3] Integration test: dashboard totals equal an independent recount on seeded data, simulation and test calls excluded in services/api/tests/integration/test_dashboard_aggregates.py

### Implementation

- [x] T043 [P] [US3] Period resolver in services/api/app/dashboard/periods.py
- [x] T044 [US3] Stats aggregate SQL and assembly in services/api/app/dashboard/service.py
- [x] T045 [US3] Quality and agent-health assembly via `CallQualityPort` in services/api/app/dashboard/service.py
- [x] T046 [US3] Dashboard endpoints and schemas in services/api/app/dashboard/router.py and services/api/app/dashboard/schemas.py
- [x] T047 [P] [US3] Dashboard page with period presets, custom range, agent multi-select in apps/web/src/routes/dashboard/DashboardPage.tsx
- [x] T048 [P] [US3] KPI tiles with sparklines in apps/web/src/routes/dashboard/KpiTiles.tsx
- [x] T049 [P] [US3] Activity and breakdown charts (calls per day, talk time, avg duration, disconnects, sentiment, channels, leaderboard, distribution) in apps/web/src/routes/dashboard/charts/
- [x] T050 [P] [US3] Quality grid and Agent health sections with empty states in apps/web/src/routes/dashboard/QualitySection.tsx
- [x] T051 [US3] Load test script for SC-002 (100k calls, p95 < 2 s) in services/api/tests/integration/test_dashboard_perf.py
- [x] T093 [P] [US3] Dashboard controls apply on change (debounced 300 ms; custom range once both dates are valid), active selection chips with "Clear all" to defaults, and Refresh reloading stats, quality and agent health with an "Updated" time, in apps/web/src/routes/dashboard/DashboardPage.tsx with tests in apps/web/src/routes/dashboard/DashboardPage.test.tsx

---

## Phase 6: User Story 4 - Compare two calls (P2)

**Independent Test**: quickstart section 5.

- [x] T052 [P] [US4] Contract test for `GET /v1/calls/{id}/compare` (with_call_id, with_simulation_run_id, both or neither is 422, cross-tenant 404) in services/api/tests/contract/test_calls_contract.py
- [x] T053 [P] [US4] Unit tests for turn alignment and flow diff in services/api/tests/unit/calls/test_compare.py
- [x] T054 [US4] Alignment, flow diff and verdict diffs via port in services/api/app/calls/compare.py
- [x] T055 [US4] Compare endpoint (simulation run resolution through 008 service when installed, else 422) in services/api/app/calls/router.py
- [x] T056 [P] [US4] Compare page at `/calls/:callId/compare` accepting `?with=` and `?sim=` in apps/web/src/routes/calls/ComparePage.tsx

---

## Phase 7: User Story 5 - Ask about your data (P3)

**Goal**: catalog-only query layer, answers with chart or table, charged once.
**Independent Test**: quickstart section 6.

### Tests (write first, must fail)

- [x] T057 [P] [US5] Contract tests for `POST /v1/analytics/chat` and `GET /v1/analytics/catalog` in services/api/tests/contract/test_analytics_chat_contract.py
- [x] T058 [P] [US5] Unit tests for MetricQuery validation (unknown metric, 5 metrics, 3 group-bys, foreign agent ID, limit 101 all rejected) in services/api/tests/unit/analytics_chat/test_metric_query.py
- [x] T059 [P] [US5] Unit tests for the compiler: golden SQL for 10 catalog queries, all values bound, only `analytics.*` relations referenced in services/api/tests/unit/analytics_chat/test_query_compiler.py
- [x] T060 [P] [US5] Unit tests for charging: one charge per Idempotency-Key, no charge on decline or provider failure, 402 at zero balance in services/api/tests/unit/analytics_chat/test_charging.py
- [x] T061 [P] [US5] Integration isolation suite: 50 hostile questions with a scripted fake model emitting adversarial tool calls; zero writes, zero ws_B rows; executor role cannot `SELECT` from `calls` directly in services/api/tests/integration/test_analytics_isolation.py

### Implementation

- [x] T062 [P] [US5] Metric and dimension catalog with labels and units in services/api/app/analytics_chat/catalog.py
- [x] T063 [P] [US5] Request, MetricQuery and answer schemas in services/api/app/analytics_chat/schemas.py
- [x] T064 [US5] MetricQuery compiler to SQLAlchemy Core in services/api/app/analytics_chat/query_compiler.py
- [x] T065 [US5] Read-only executor (role switch, `SET TRANSACTION READ ONLY`, workspace setting, 3 s timeout, 100-row cap) in services/api/app/analytics_chat/executor.py
- [x] T066 [US5] Assistant loop (tool calling through `llms` client, max 3 queries, server-copied chart/table data, decline path) in services/api/app/analytics_chat/assistant.py
- [x] T067 [US5] Audit model and idempotent replay in services/api/app/analytics_chat/models.py
- [x] T068 [US5] Endpoint with balance pre-check, rate limit (20/min/user) and `billing.charge_feature("analytics_chat")` in services/api/app/analytics_chat/router.py
- [x] T069 [P] [US5] Purge job for audit rows older than 30 days in services/api/app/analytics_chat/jobs.py
- [x] T070 [P] [US5] Floating Ask panel (420 px, expand to split view, New chat, suggested questions from catalog) in apps/web/src/app/assistant/AskPanel.tsx
- [x] T071 [P] [US5] Chart and table renderers plus "How this was computed" disclosure in apps/web/src/app/assistant/AnswerView.tsx
- [x] T094 [P] [US5] Ask panel error states from 402 (add funds link), 429 and 503 (retry) and declined answers (example questions), keeping the typed question, in apps/web/src/app/assistant/AskPanel.tsx with tests in apps/web/src/app/assistant/AskPanel.test.tsx

---

## Phase 8: User Story 6 - Voice copilot (P3)

**Independent Test**: quickstart section 7.

### Tests (write first, must fail)

- [x] T072 [P] [US6] Contract tests for stream-token, transcribe, interpret in services/api/tests/contract/test_voice_commands_contract.py
- [x] T073 [P] [US6] Unit tests for interpretation validation (unknown route, unregistered action, bad params, unknown copilot target all downgrade to decline; highlight_element must be a registered key) in services/api/tests/unit/voice_commands/test_interpreter.py
- [x] T074 [P] [US6] Integration benchmark harness for the 60-utterance set (SC-007) with recorded model fixtures in services/api/tests/integration/test_voice_interpret.py

### Implementation

- [x] T075 [P] [US6] STT adapter protocol and Deepgram adapter (mint 60 s listen-only key, batch transcribe) in services/api/app/voice_commands/stt/base.py and services/api/app/voice_commands/stt/deepgram.py
- [x] T076 [P] [US6] Route allowlist mirrored from the web router in services/api/app/voice_commands/routes_allowlist.py
- [x] T077 [US6] Interpreter (model call, validation, downgrade, usage record `voice_copilot`) in services/api/app/voice_commands/interpreter.py
- [x] T078 [US6] Endpoints with rate limit 30/min/user and 30 s / 2 MB clip limits in services/api/app/voice_commands/router.py
- [x] T079 [P] [US6] Log model and 30-day purge job in services/api/app/voice_commands/models.py and services/api/app/voice_commands/jobs.py
- [x] T080 [P] [US6] Push-to-talk controller (Space outside text fields, mic button, states, typing fallback) in apps/web/src/app/copilot/VoiceCopilot.tsx
- [x] T081 [P] [US6] Browser STT client adapter for Deepgram in apps/web/src/app/copilot/stt/deepgram.ts
- [x] T082 [P] [US6] Page action registry hook (`useRegisterVoiceActions`) and event dispatch for navigate, route_to_copilot, ui_action in apps/web/src/app/copilot/actionRegistry.ts
- [x] T083 [US6] Register `filter_calls` on Call History and `ask_analytics` on the dashboard in apps/web/src/routes/calls/CallHistoryPage.tsx and apps/web/src/routes/dashboard/DashboardPage.tsx

---

- [x] T095 [US6] Mint the copilot STT key lazily on the first push-to-talk (never on page load) and check microphone permission before requesting it, showing the typing fallback when denied, in `apps/web/src/app/copilot/VoiceCopilot.tsx`; architecture v1.2 section 7

## Phase 9: Polish and cross-cutting

- [x] T084 [P] OpenTelemetry spans with `call_id` on detail, recording and compare endpoints in services/api/app/calls/router.py
- [x] T085 [P] Accessibility pass on table, drawer, charts (keyboard, labels, chart data tables) in apps/web/src/routes/calls/ and apps/web/src/routes/dashboard/
- [x] T086 Call list perf test for SC-001 (1M calls) in services/api/tests/integration/test_calls_perf.py
- [x] T087 Run quickstart.md end to end and fix drift

---

## Dependencies and execution order

- Phase 1, then Phase 2, block everything.
- US1 and US2 are independent after Phase 2 and together form the MVP.
- US3 needs only Phase 2 (quality sections show empty states until 007 registers its port).
- US4 reuses US2 loaders (T029).
- US5 needs Phase 1 views (T004); independent of US1 to US4.
- US6 is independent; T083 touches pages from US1 and US3, so run it after T017 and T047.

## Parallel example: User Story 2

```bash
# Tests together
T022 test_calls_contract.py, T023 test_recordings_contract.py, T024 test_cost_view.py,
T025 test_transcript_text.py, T026 recordings/test_service.py
# Then implementation in parallel
T027 cost_view.py, T028 transcript_text.py, T031 recordings/service.py,
T033 to T037 web components
```

## Implementation strategy

1. Setup and Foundational.
2. US1 + US2 (MVP): operators can find and read any call. Demo.
3. US3 dashboard, then US4 compare.
4. US5 and US6 last; both are additive overlays in the shell.
