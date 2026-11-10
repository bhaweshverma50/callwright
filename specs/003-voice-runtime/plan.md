# Implementation Plan: Voice Runtime

**Branch**: `003-voice-runtime` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-voice-runtime/spec.md`

## Summary

Deliver the call engine: a LiveKit Agents (Python) worker that runs any agent version as a
VAD, STT, LLM, TTS pipeline with per-vendor adapters, plus the API side that admits calls
(credit, concurrency, pricing coverage), owns the call lifecycle, ingests per-turn latency and
usage events, records audio through LiveKit egress (unless the call's effective recording
setting, resolved at admission from the workspace default and the agent override, is off), runs the ordered and idempotent post-call
pipeline, and sends signed customer webhooks with retries. The browser test call is the channel
delivered end to end here; 010 adds phone and WhatsApp on the same admission, claim and event
paths. Tools/RAG (005) and flows (004) plug into extension points defined here. An offline
scripted-caller harness and a real-vendor latency benchmark guard the hot path.

## Technical Context

**Language/Version**: Python 3.12 (API and worker); TypeScript 5 (web panel)
**Primary Dependencies**: API: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, httpx,
`livekit-api` (server SDK: rooms, dispatch, egress, webhook verification). Worker:
`livekit-agents` 1.x with plugins `silero`, `turn-detector`, `deepgram`, `assemblyai`, `sarvam`,
`openai` (OpenAI and Azure OpenAI), `anthropic`, `elevenlabs`, `cartesia`; in-house adapters
for Fish Audio TTS and Sanas / ai-coustics NC where no plugin exists (research R8). Web:
`livekit-client`, TanStack Query.
**Storage**: PostgreSQL 16 with RLS (`calls`, `call_events`, `call_pipeline_steps`,
`webhook_signing_secrets`, `webhook_deliveries`, `idempotency_keys`); Redis (arq queues and
deferred retries); S3-compatible bucket for recordings (SSE-KMS).
**Testing**: pytest + pytest-asyncio; schemathesis-style contract tests against the assembled
OpenAPI; offline harness (`services/voice-worker/tests/harness`) with fake adapters and virtual
clock; benchmark mode against `livekit-server --dev` and real vendors; Vitest for the web hook.
**Target Platform**: Linux containers; LiveKit Cloud (or self-hosted LiveKit with egress).
**Project Type**: Web service + realtime worker + SPA (monorepo per research/architecture.md).
**Performance Goals**: Turn latency p50 at most 800 ms, p95 at most 1,500 ms on the default
stack (Principle II); greeting within 3 s of browser connect (p95); events ingest p95 under
50 ms per batch; first webhook attempt within 5 s of the event (p99).
**Constraints**: Worker stateless and horizontally scaled; worker never holds database or
storage credentials; every vendor behind an adapter; AgentConfig read-only at runtime.
**Scale/Scope**: v1 target 500 concurrent calls per region, roughly 25 call_events rows per call
minute; 5 API modules, about 12 worker modules, 1 web route.

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design.*

| Gate | Principle | How this plan satisfies it | Status |
|---|---|---|---|
| Vendor behind adapter | I | `worker/adapters/{stt,llm,tts,nc}/<vendor>.py` plus `registry.py`; config chooses provider strings; a new vendor is one adapter file, one `adapters/catalog.json` entry and one pricing row (001); no schema change (usage arrays are keyed by provider and model). Runtime reads the frozen `AgentVersion` and never writes it. | Pass |
| Latency impact stated | II | This feature is the hot path. Every turn stores `e2e_ms` and components in `call_events`. Benchmark gate T105 (with T102, T103) blocks merges touching `services/voice-worker/worker/**` on p50 800 ms and p95 1,500 ms and on no more than 10% regression versus `benchmarks/baseline.json`. Added hot-path work (pronunciation transform, metrics hooks) is O(text) and measured in the same benchmark. Event posting is async and off the audio path. | Pass |
| Metering impact stated | III | Worker meters STT audio, LLM input, cached and output tokens, TTS characters and NC seconds as cumulative snapshots; API computes `billable_seconds` with whole-second round-up from connected to ended; `price_and_charge` calls 001's pricing and ledger with idempotency key `call_charge:{call_id}`; mid-call guard ends calls on credit exhaustion. Ringing and queue time are never billed. | Pass |
| Measurability path | IV | Full transcript, tool and flow items, per-turn latency and the immutable version id are stored per call, which 007 evaluators and 008 simulations consume; pipeline steps `analyze` and `evaluate` are reserved hooks for 007. The harness replays scripted callers against any version. | Pass |
| Tenancy and privacy | V | RLS on every new table; internal endpoints derive workspace from the call row, not the body; recordings encrypted (SSE-KMS) and served only via 10-minute signed URLs (006); webhook secret stored in `secrets`, returned masked except once on rotate; SSRF guard on customer URLs; service token for worker calls; LiveKit tokens scoped to one room with microphone-only publish. Recording opt-out (spec Clarifications 2026-10-16, FR-043, FR-044): admission resolves `calls.recording_enabled` from 002's `advanced.recording` override and 001's `workspaces.recording_default`; when false no egress is started, `recording_status = not_recorded`, and transcripts and metrics are still stored. | Pass |
| Complexity justified | VI | No new deployables or queues: API + arq jobs + one worker, as in architecture section 1. Pipeline orchestration uses a step table, not a workflow engine. Additive worker files and one new ID prefix are listed in Complexity Tracking. | Pass |
| Contract and money tests | VII | Contract tests for all five fragments written first (T021, T022, T023, T073, T084); money tests first: admission credit and concurrency (T045, T046), billable-seconds rounding (T026), usage snapshot monotonicity (T025), mid-call credit guard (T047), charge idempotency under pipeline replay (T075). Offline harness (US7) runs in CI. | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/003-voice-runtime/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1, one OpenAPI 3.1 fragment per API module
│   ├── sessions.yaml
│   ├── calls.yaml
│   ├── call_events.yaml
│   ├── webhooks_out.yaml
│   └── livekit_hooks.yaml
├── checklists/requirements.md
└── tasks.md             # Phase 2
```

### Source Code (repository root)

```text
services/api/app/
├── core/
│   ├── livekit.py            # NEW shared LiveKit server client (rooms, dispatch, egress, tokens, webhook receiver)
│   ├── idempotency.py        # NEW if 001 has not created it (Idempotency-Key storage and replay)
│   └── url_guard.py          # NEW SSRF guard for outbound HTTP to customer URLs
├── sessions/                 # browser test calls
│   ├── router.py  schemas.py  service.py
├── calls/                    # write side (006 adds read routes to router.py)
│   ├── models.py             # Call, CallPipelineStep, enums, state machine helpers
│   ├── schemas.py
│   ├── service.py            # admit(), claim(), transition(), inbound router protocol
│   ├── router.py             # POST /v1/internal/calls/claim
│   ├── pipeline.py           # step registry and runner (finalize, price, analyze, evaluate, notify, complete)
│   └── jobs.py               # run_pipeline, start_recording, reap_stuck_calls (cron)
├── call_events/
│   ├── models.py  schemas.py  service.py  router.py
├── webhooks_out/
│   ├── models.py  schemas.py  service.py  router.py  jobs.py
│   └── signing.py            # sign()/verify() helpers, shared with tests and docs
├── livekit_hooks/
│   ├── router.py  service.py
└── migrations/versions/
    └── 0003_voice_runtime.py

services/api/tests/
├── contract/   test_sessions_contract.py  test_calls_internal_contract.py
│               test_call_events_contract.py  test_webhooks_out_contract.py  test_livekit_hooks_contract.py
├── unit/       test_admission.py  test_billable_seconds.py  test_usage_snapshot.py
│               test_credit_guard.py  test_variables.py  test_signing.py  test_url_guard.py
│               test_call_state_machine.py  test_pipeline_runner.py
└── integration/ test_web_call_flow.py  test_admission_race.py  test_pipeline_idempotency.py
                 test_webhook_retries.py  test_reaper.py  test_livekit_hooks.py
                 test_rls_voice_runtime.py  test_events_ingest_perf.py  tools/flaky_receiver.py

services/voice-worker/
├── worker/
│   ├── entry.py              # job entry: claim, build session, channel handling, shutdown
│   ├── pipeline.py           # session assembly from RuntimeConfig, turn-taking mapping
│   ├── metrics.py            # per-turn latency, usage meters, event batching to the API
│   ├── internal_api.py       # NEW: typed client for /v1/internal/* (claim, events)
│   ├── settings.py           # NEW: worker settings
│   ├── call_behavior.py      # NEW: inactivity and duration timers, DTMF collector, voicemail
│   ├── audio.py              # NEW: background audio, pronunciation streaming transform
│   ├── adapters/
│   │   ├── registry.py  catalog.json
│   │   ├── stt/{deepgram,assemblyai,sarvam}.py
│   │   ├── llm/{openai,azure_openai,anthropic}.py
│   │   ├── tts/{elevenlabs,cartesia,fishaudio}.py
│   │   └── nc/{sanas,ai_coustics,none}.py
│   ├── tools/__init__.py     # extension point: ToolProvider protocol, CallControl, NullToolProvider (005 implements)
│   └── flow/__init__.py      # extension point: FlowRunner protocol, NullFlowRunner (004 implements)
└── tests/
    ├── unit/   test_turn_mapping.py  test_pronunciation.py  test_dtmf_collector.py
    │           test_timers.py  test_metrics.py  test_registry.py  test_variables_render.py
    └── harness/
        ├── runner.py  fakes.py  clock.py  script_schema.py
        ├── scripts/*.yaml
        ├── test_scenarios.py
        ├── benchmark.py
        └── benchmarks/{callset.yaml,baseline.json,fixtures/*.wav}

apps/web/src/
├── routes/agents/AgentTestingPage.tsx       # /agents/:id/testing
├── routes/agents/components/WebCallPanel.tsx   # reusable panel (also embedded by 002's editor)
├── routes/agents/components/TestVariablesDialog.tsx
├── routes/agents/components/Keypad.tsx
├── routes/agents/hooks/useWebCall.ts
└── api/                                      # regenerated client
```

**Structure Decision**: The monorepo layout from research/architecture.md section 2 is used as
is. API modules match the 003 row of the module ownership table. Worker extension points live
in the existing `tools/` and `flow/` packages so 005 and 004 implement them in place.

### Extension points (for 004, 005, 007, 010)

| Point | Location | Contract | Default without the owning feature |
|---|---|---|---|
| `ToolProvider.tools_for(runtime, control) -> list[FunctionTool]` | `worker/tools/__init__.py` | 005 returns function tools (end_call, transfer, press_digit, http, kb_search) built from `config.tool_ids` and `config.kb_ids`; tool activity reported via `control.report_tool(...)` | `NullToolProvider`: no tools |
| `CallControl` | `worker/tools/__init__.py` | `hang_up(reason)`, `say(text, allow_interruptions)`, `send_dtmf(digits)`, `report_tool(...)`, `report_transition(...)`, `apply_overrides(overrides)` (FR-046, research R22), `room`, `call_id` | implemented here |
| `FlowRunner.build_agent(runtime, control, tools) -> Agent` | `worker/flow/__init__.py` | 004 returns the entry agent for a flow and drives handoffs | `NullFlowRunner`: fails flow calls with `flow_runtime_unavailable` |
| `InboundRouter.resolve(channel, sip_attrs, route_ref) -> InboundRoute` | `services/api/app/calls/service.py` | 010 registers routers for `sip_inbound` and `whatsapp` returning workspace, agent, variables, phone_number_id / whatsapp_channel_id | none registered: SIP claims refused with `error` |
| `OutboundDialProvider.dial_spec(call) -> OutboundDial` | `services/api/app/calls/service.py` | 010 supplies trunk and numbers for `sip_outbound` claims | none: outbound claims refused |
| Pipeline handlers `analyze`, `evaluate` | `services/api/app/calls/pipeline.py` | 007 registers `async def handler(call_id, session)` | step `skipped` |
| `recording_state(call) -> CallRecordingState` | `services/api/app/calls/service.py` | 006's recording URL endpoints call it; returns `not_recorded` with no URL when `recording_enabled` is false (schema in `contracts/calls.yaml`) | implemented here |

### Interfaces consumed from 001 and 002 (recording setting)

003 does not own these fields; it reads them once per call at admission (`calls.service.admit`).

| Field | Owner | Type and default | Use in 003 |
|---|---|---|---|
| `workspaces.recording_default` | 001 (workspace settings, editable through 001's workspace settings API) | boolean, not null, default `true` | used when the agent override is `inherit` |
| `AgentConfig.advanced.recording` | 002 (frozen in each `agent_versions.config`) | string enum `inherit`, `on`, `off`; default `inherit` | `on` or `off` wins over the workspace default |

Resolution: `recording_enabled = (override == "on") or (override == "inherit" and workspace.recording_default)`.
A version whose config predates the field is read as `inherit`. The result and its source
(`recording_setting_source`: `workspace` or `agent`) are written to the call row and never
recomputed; later changes to either setting affect only new calls.

## Complexity Tracking

| Deviation from architecture.md | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Extra worker modules `internal_api.py`, `settings.py`, `call_behavior.py`, `audio.py` (not in section 2 layout) | Keep `entry.py` and `pipeline.py` small and unit-testable; timers and DTMF need a fake clock in the harness | Folding into `entry.py` makes it untestable without a room |
| `adapters/registry.py` and `adapters/catalog.json` | API must reject unsupported vendors at admission without importing worker code | Hard-coding the vendor list in the API duplicates it |
| New ID prefix `whd_` for webhook deliveries | Deliveries are user-visible and re-sendable by id | Reusing `call_` ids cannot identify one of several deliveries per call |
| `core/livekit.py`, `core/url_guard.py`, possibly `core/idempotency.py` in a 001-owned package | Shared by 003 and 010 (LiveKit) and 005 (URL guard); idempotency is cross-cutting | Duplicating per module; coordinate with 001's plan |
| `calls/pipeline.py` step table instead of plain chained jobs | Architecture section 6 requires per-step idempotency keyed by call and step, plus visibility of failed non-blocking steps | Chained arq jobs alone lose step state on retry |
