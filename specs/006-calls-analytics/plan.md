# Implementation Plan: Calls and Analytics

**Branch**: `006-calls-analytics` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/006-calls-analytics/spec.md`

## Summary

Give operators the read side of their calls: a filterable, sortable, paginated call history with
cross-page selection handed to simulations; a call detail view (transcript with tool items,
signed-URL recording, summary, sentiment, analysis values, measured per-turn latency, flow path,
itemised cost with surcharge lines); a two-call compare page; a fleet dashboard; an "ask about
your data" assistant built on a typed, catalog-only query layer over read-only RLS views; and a
push-to-talk voice copilot with browser-direct streaming transcription and server-validated
intents. Quality data (verdicts, labels) is read through a port that 007 implements, so this
feature ships first with correct empty states.

## Technical Context

**Language/Version**: Python 3.12 (API), TypeScript 5 (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2 Core and ORM, Alembic, arq, boto3
(S3 presign), httpx; web: React, Vite, TanStack Query, React Router, Tailwind + Radix, Recharts,
`@tanstack/react-table`, `@tanstack/react-virtual`
**Storage**: PostgreSQL 16 with RLS (calls, call_events, new audit tables, `analytics` views);
Redis (rate limits); S3-compatible storage (recordings, read only)
**Testing**: pytest (unit, contract with `openapi-core`, integration against a real Postgres with
RLS enabled); Vitest + Testing Library + MSW (web)
**Target Platform**: Linux containers (API), evergreen browsers (web)
**Project Type**: web application (API service + SPA)
**Performance Goals**: call list first page p95 < 1.5 s at 1M calls per workspace; dashboard p95
< 2 s at 100k calls per window; recording playback start < 2 s; voice interpret p95 < 1.5 s;
analytics answer p95 < 15 s
**Constraints**: no model-written SQL is ever executed (FR-024); signed recording URLs <= 10 min;
STT credential TTL <= 60 s; analytics queries read-only, 3 s statement timeout, <= 100 rows
**Scale/Scope**: 3 web routes (`/dashboard`, `/calls`, `/calls/:id/compare`), 2 shell overlays
(assistant panel, voice copilot), 5 API modules, 15 endpoints

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design: PASS.*

| Principle | Gate | Status |
|---|---|---|
| I. Provider-agnostic | Assistant and copilot models go through the `llms` completion client (002) with model ids from settings; copilot STT goes through `voice_commands/stt/<vendor>.py` adapters (API) and `app/copilot/stt/<vendor>.ts` (web). No vendor in feature code. | PASS |
| II. Latency | Not on the call hot path. Feature only reads turn timings; it shows measured parts and never substitutes values (research R2). Copilot interpret target p95 < 1.5 s. | PASS |
| III. Metering | Analytics questions charged through `billing.charge_feature("analytics_chat")` once per Idempotency-Key; voice copilot usage recorded as feature `voice_copilot` (billable rate from catalog, default 0). Cost view reads 001's stored lines, never recomputes. | PASS |
| IV. Measurability | Dashboard pass rates and agent health expose evaluator results; compare page shows verdict diffs; assistant shows "How this was computed". | PASS |
| V. Tenancy and privacy | All reads under RLS; `analytics` views use `security_invoker`; assistant role has view-only grants and a read-only transaction; recordings via 10-minute presigned URLs; assistant never sees transcripts or phone numbers; STT credential scoped and short-lived. | PASS |
| VI. Simplicity | No rollup tables, no new service, no new queue. One port interface for 007 data (Complexity Tracking). | PASS with 1 entry |
| VII. Contracts and money | Contract tests for all 5 modules; test-first for cost view math (avg rate, surcharge multiplier display), dashboard aggregation, MetricQuery compiler and charge idempotency. | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/006-calls-analytics/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── calls.yaml
│   ├── recordings.yaml
│   ├── dashboard.yaml
│   ├── analytics_chat.yaml
│   └── voice_commands.yaml
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/
├── calls/                 # read side (003 owns the write side in the same module)
│   ├── router.py          # GET /v1/calls, /{id}, /transcript, /turn-latencies, /flow-transitions, /compare
│   ├── schemas.py
│   ├── queries.py         # list filters, sort, pagination; detail loaders
│   ├── cost_view.py       # maps 001 cost lines to header, lines, surcharges
│   ├── compare.py         # turn alignment and flow diff
│   ├── transcript_text.py # plain-text copy format
│   └── quality_port.py    # CallQualityPort protocol + NullCallQualityPort
├── recordings/
│   ├── router.py          # GET /v1/calls/{id}/recording
│   └── service.py         # presign, retention and processing checks
├── dashboard/
│   ├── router.py
│   ├── schemas.py
│   ├── periods.py         # preset and custom window resolution in a timezone
│   └── service.py         # aggregate SQL, zero-fill, top-N + others, agent health
├── analytics_chat/
│   ├── router.py
│   ├── schemas.py         # ChatRequest, MetricQuery, ChatAnswer
│   ├── catalog.py         # metric and dimension catalog
│   ├── query_compiler.py  # MetricQuery -> SQLAlchemy Core over analytics.* views
│   ├── executor.py        # read-only session as cw_analytics_reader
│   ├── assistant.py       # tool-calling loop (max 3 queries), answer assembly
│   ├── models.py          # analytics_chat_requests
│   └── jobs.py            # purge audit rows older than 30 days
├── voice_commands/
│   ├── router.py
│   ├── schemas.py
│   ├── stt/base.py        # SttCommandAdapter protocol
│   ├── stt/deepgram.py
│   ├── routes_allowlist.py
│   ├── interpreter.py     # model call + server-side validation/downgrade
│   ├── models.py          # voice_command_logs
│   └── jobs.py            # purge logs older than 30 days
└── migrations/versions/
    └── 0601_calls_analytics.py   # indexes, audit tables, analytics schema, role, views

services/api/tests/
├── unit/calls/  unit/dashboard/  unit/analytics_chat/  unit/voice_commands/
├── contract/test_calls_contract.py, test_recordings_contract.py, test_dashboard_contract.py,
│   test_analytics_chat_contract.py, test_voice_commands_contract.py
└── integration/test_calls_read.py, test_dashboard_aggregates.py, test_analytics_isolation.py,
    test_voice_interpret.py

apps/web/src/
├── routes/calls/          # CallHistoryPage, filters, columns, CallDetailDrawer, ComparePage
├── routes/dashboard/      # DashboardPage, KPI tiles, charts, quality sections
├── app/assistant/         # AskPanel (floating + split view), chart/table renderers
├── app/copilot/           # push-to-talk, state orb, stt/<vendor>.ts, action registry
└── api/                   # regenerated client from contracts
```

**Structure Decision**: Web application layout from architecture.md section 2. Call detail is a
drawer on `/calls` addressed by `?call=<call_id>` so it is deep-linkable without adding a route
outside the module table. The assistant and copilot mount into the 001 shell from
`apps/web/src/app/`.

## Phase 0 and Phase 1 outputs

- [research.md](./research.md): R1 to R12 (query strategy, latency, quality port, constrained
  query layer, model access, charging, STT, interpretation, recording links, charts, origin,
  contract tests).
- [data-model.md](./data-model.md): consumed records, owned audit tables, indexes, `analytics`
  views, read models.
- [contracts/](./contracts/): one OpenAPI 3.1 fragment per module.
- [quickstart.md](./quickstart.md): end-to-end validation script.

## Integration points

- **003**: must provide `calls.origin`, `agent_name_snapshot`, per-call latency summary and
  `call_events` kinds listed in data-model.md.
- **001**: `call_cost_lines`, `billing.charge_feature`, pricing catalog feature rates
  (`analytics_chat`, `voice_copilot`), workspace retention setting.
- **002**: `llms` completion client with tool calling and JSON-schema output.
- **007**: registers `EvalCallQualityPort`; replaces `analytics.evaluator_verdicts_v`.
- **008**: `POST` experiment endpoint receiving `call_ids[]`; resolves `srun_` to its output call
  for `/calls/{id}/compare?with_simulation_run_id=`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `CallQualityPort` interface with a null implementation | 006 must render quality data owned by 007, and 007 depends on 006 | Writing quality columns into 003's `calls` table makes two modules write one table; moving quality sections to 007 splits one page across contracts |
| Separate DB role `cw_analytics_reader` and `analytics` schema views | Defence in depth for the assistant (FR-024), beyond RLS | RLS alone does not stop reads of non-tenant tables or writes if the compiler has a bug |
| API-side STT command adapters separate from voice-worker adapters | Copilot needs credential minting and batch transcription, which the worker's streaming adapters do not do | Reusing worker adapters would pull LiveKit Agents into the API image |
