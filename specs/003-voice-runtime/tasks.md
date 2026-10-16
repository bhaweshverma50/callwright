---
description: "Task list for 003-voice-runtime"
---

# Tasks: Voice Runtime

**Input**: Design documents from `specs/003-voice-runtime/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required. Principle VII: contract tests and money tests are written first and must
fail before implementation; the voice worker has an offline harness. Principle II: the latency
benchmark is a merge gate (T105).

**Organization**: Grouped by user story (spec.md priorities). Paths follow
research/architecture.md section 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US7 from spec.md

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Create the worker package: `services/voice-worker/pyproject.toml` (Python 3.12, `livekit-agents` 1.x with `silero`, `turn-detector`, `deepgram`, `openai`, `elevenlabs` plugins, pytest, pytest-asyncio, ruff, mypy) and `services/voice-worker/worker/__init__.py`
- [ ] T002 [P] Add `livekit-api` and `httpx` to `services/api/pyproject.toml`
- [ ] T003 [P] Add `livekit-client` to `apps/web/package.json`
- [ ] T004 [P] Add settings `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `CALLWRIGHT_SERVICE_TOKEN`, `CREDIT_GRACE_USD`, `RECORDINGS_BUCKET`, `WORKER_AGENT_NAME` to `services/api/app/core/config.py`
- [x] T005 [P] Create worker settings (internal API URL, service token, agent name, heartbeat interval) in `services/voice-worker/worker/settings.py`
- [ ] T006 [P] Add CI workflow `.github/workflows/voice-worker.yml` running ruff, mypy, `tests/unit` and `tests/harness` for `services/voice-worker`

---

## Phase 2: Foundational (Blocking Prerequisites)

**No user story work starts until this phase is complete.**

- [ ] T007 Write migration `services/api/app/migrations/versions/0003_voice_runtime.py`: enums (`call_channel`, `call_direction`, `call_status`, `disconnect_reason`, `recording_status` (including `not_recorded`), `recording_setting_source`, `pipeline_status`, `call_event_type`, `pipeline_step`, `step_status`, `webhook_event`, `delivery_status`), tables `calls`, `call_events`, `call_pipeline_steps`, `webhook_signing_secrets`, `webhook_deliveries`, `idempotency_keys` (skip if 001 created it), all indexes and RLS policies from data-model.md
- [ ] T008 [P] Create `Call` and `CallPipelineStep` ORM models, enums and the guarded `transition(call_id, expected, new, **fields)` helper in `services/api/app/calls/models.py`
- [ ] T009 [P] Create `CallEvent` ORM model in `services/api/app/call_events/models.py`
- [ ] T010 [P] Create `WebhookSigningSecret` and `WebhookDelivery` ORM models in `services/api/app/webhooks_out/models.py`
- [ ] T011 [P] Implement Idempotency-Key storage and replay dependency (24 h, request hash check) in `services/api/app/core/idempotency.py` (reuse 001's if present)
- [ ] T012 [P] Implement LiveKit server client wrapper (create/delete room, create agent dispatch, mint scoped participant token, start room-composite egress, webhook receiver) in `services/api/app/core/livekit.py`
- [ ] T013 [P] Add `require_service()` service-token dependency to `services/api/app/core/auth.py`
- [x] T014 [P] Implement typed internal API client (`claim()`, `post_events()` with retry and backoff, control handling) in `services/voice-worker/worker/internal_api.py`
- [x] T015 [P] Implement adapter registry with capability records and `UnsupportedVendor`, plus `catalog.json` listing supported `(kind, provider, models)` in `services/voice-worker/worker/adapters/registry.py` and `services/voice-worker/worker/adapters/catalog.json`
- [x] T016 [P] Define `ToolProvider`, `CallControl` protocols and `NullToolProvider` in `services/voice-worker/worker/tools/__init__.py`
- [x] T017 [P] Define `FlowRunner` protocol and `NullFlowRunner` in `services/voice-worker/worker/flow/__init__.py`
- [ ] T018 Define `InboundRouter` and `OutboundDialProvider` registries and the call state-transition service in `services/api/app/calls/service.py` (depends on T008)
- [x] T019 Build the offline harness core: virtual clock `clock.py`, fake adapters and fake room transport `fakes.py`, YAML script schema `script_schema.py`, scenario runner `runner.py` in `services/voice-worker/tests/harness/`
- [ ] T020 Register 003 jobs and crons (pipeline, recording, webhook delivery, reaper, purge) in `services/api/app/jobs.py` `WorkerSettings` (create if absent)

**Checkpoint**: schema, shared clients, extension points and harness core exist.

---

## Phase 3: User Story 1 - Talk to an agent from the browser (Priority: P1) MVP

**Goal**: Operator starts a browser test call with variables, hears the agent, sees live state
and transcript, hangs up; the call, its events and latency rows are stored.

**Independent Test**: Start a test call on a draft, exchange three turns, end; call row has
channel `web`, status `ended`, reason `user_hangup`, one `turn` event per agent reply.

### Tests for User Story 1 (write first, must fail)

- [ ] T021 [P] [US1] Contract test for `POST /v1/sessions/web-call` against `contracts/sessions.yaml` in `services/api/tests/contract/test_sessions_contract.py`
- [ ] T022 [P] [US1] Contract test for `POST /v1/internal/calls/claim` against `contracts/calls.yaml` in `services/api/tests/contract/test_calls_internal_contract.py`
- [ ] T023 [P] [US1] Contract test for `POST /v1/internal/calls/{call_id}/events` against `contracts/call_events.yaml` in `services/api/tests/contract/test_call_events_contract.py`
- [ ] T024 [P] [US1] Unit tests for variable resolution order, built-in protection, validation limits and missing-name recording in `services/api/tests/unit/test_variables.py`
- [ ] T025 [P] [US1] Money test: cumulative usage snapshots are monotonic, lower `seq` ignored, duplicates harmless in `services/api/tests/unit/test_usage_snapshot.py`
- [ ] T026 [P] [US1] Money test: `billable_seconds` = ceil(connected to ended), 4.2 s bills 5 s, ringing and queue excluded, never-connected bills 0 in `services/api/tests/unit/test_billable_seconds.py`
- [x] T027 [P] [US1] Harness scenarios for agent-first greeting with variables, empty-greeting generated opening, and caller-first silence in `services/voice-worker/tests/harness/scripts/greeting.yaml` and `services/voice-worker/tests/harness/test_scenarios.py`
- [ ] T028 [P] [US1] Integration test: web call request, claim, scripted events, caller leaves, call `ended` with `user_hangup` in `services/api/tests/integration/test_web_call_flow.py`

### Implementation for User Story 1

- [ ] T029 [US1] Implement `admit()` base path (resolve version via 002 `snapshot_for_test` / published / explicit id, resolve variables and built-ins, insert `queued` call, idempotency key) in `services/api/app/calls/service.py`
- [ ] T030 [US1] Implement web-call schemas and service (admit, create room `call-{call_id}`, dispatch `callwright-voice` with `{call_id}`, mint 15-minute token) in `services/api/app/sessions/schemas.py` and `services/api/app/sessions/service.py`
- [ ] T031 [US1] Implement `POST /v1/sessions/web-call` with Idempotency-Key in `services/api/app/sessions/router.py`
- [ ] T032 [US1] Implement `claim()` (pre-admitted path, job-id idempotency, RuntimeConfig assembly) and `POST /v1/internal/calls/claim` in `services/api/app/calls/service.py` and `services/api/app/calls/router.py`
- [ ] T033 [US1] Implement event ingest (insert ON CONFLICT DO NOTHING, status transitions via T018, usage snapshot by seq, `last_heartbeat_at`, `billable_seconds` on end) and router in `services/api/app/call_events/service.py`, `services/api/app/call_events/schemas.py`, `services/api/app/call_events/router.py`
- [x] T034 [P] [US1] Deepgram STT adapter in `services/voice-worker/worker/adapters/stt/deepgram.py`
- [x] T035 [P] [US1] OpenAI and Azure OpenAI LLM adapters in `services/voice-worker/worker/adapters/llm/openai.py` and `services/voice-worker/worker/adapters/llm/azure_openai.py`
- [x] T036 [P] [US1] ElevenLabs TTS adapter in `services/voice-worker/worker/adapters/tts/elevenlabs.py`
- [ ] T037 [P] [US1] Sanas and passthrough NC adapters in `services/voice-worker/worker/adapters/nc/sanas.py` and `services/voice-worker/worker/adapters/nc/none.py`
  - Open: the adapter, its `SanasEngine` contract, the `SANAS_*` settings and a fake engine (`tests/unit/test_nc_sanas.py`) are done, and `none.py` is done. FR-020 is not met for Sanas until the vendor SDK is wired: without it the filter passes audio through unchanged, meters nothing and records an `nc_passthrough` warning. Remaining: an engine module that calls `register_engine()` with the Sanas SDK (key, endpoint, model rate), then a live check that `usage.nc` matches processed audio.
- [x] T038 [US1] Implement session assembly from RuntimeConfig (VAD, STT, LLM, TTS, NC via registry; prompt and greeting variable rendering; tools from `ToolProvider`; flow agents via `FlowRunner`) in `services/voice-worker/worker/pipeline.py`
- [x] T039 [US1] Implement per-turn latency (direct `e2e_ms`, component metrics, greeting latency), usage meters, transcript items and event batching with 10 s heartbeat in `services/voice-worker/worker/metrics.py`
- [x] T040 [US1] Implement job entry: prewarm models, claim, web channel handling (60 s caller join timeout, `in_progress` on join, `user_hangup` on leave), start speaker, final status post, shutdown in `services/voice-worker/worker/entry.py`
- [ ] T041 [P] [US1] Implement `useWebCall` (request session, connect, agent state from `lk.agent.state`, transcript from `lk.transcription`, end) in `apps/web/src/routes/agents/hooks/useWebCall.ts` with tests in `apps/web/src/routes/agents/hooks/useWebCall.test.ts`
- [ ] T042 [P] [US1] Implement variables dialog pre-filled with defaults in `apps/web/src/routes/agents/components/TestVariablesDialog.tsx`
- [ ] T043 [US1] Implement `WebCallPanel` (orb, live transcript, end button) and `/agents/:id/testing` page, register the route in `apps/web/src/app/router.tsx`, files `apps/web/src/routes/agents/components/WebCallPanel.tsx` and `apps/web/src/routes/agents/AgentTestingPage.tsx`
- [ ] T044 [US1] Add the five 003 fragments to the `contracts/openapi.yaml` assembly and regenerate the TS client in `apps/web/src/api/`
- [ ] T118 [US1] Microphone precheck (FR-047) in `apps/web/src/routes/agents/hooks/useWebCall.ts` and `WebCallPanel.tsx`: request microphone permission before `POST /v1/sessions/web-call`; on denial show how to allow it and send no request; Playwright test with permission denied in `apps/web/tests/e2e/test-call-mic.spec.ts` asserts no session request and no call row

**Checkpoint**: US1 works end to end with the default stack.

---

## Phase 4: User Story 2 - Calls start only when allowed and always end cleanly (Priority: P1)

**Goal**: Admission checks, refusal records, mid-call credit guard, silence and duration limits,
stuck-call reaping.

**Independent Test**: Concurrency 1 refuses the second call; zero balance refuses; max duration
ends with `max_duration_reached`.

### Tests for User Story 2 (write first, must fail)

- [ ] T045 [P] [US2] Money test: refusal at balance 0 and below, refusal record with reason, email-unverified and unpriced-config refusals in `services/api/tests/unit/test_admission.py`
- [ ] T046 [P] [US2] Money test: 50 concurrent admissions for the last slot admit exactly one in `services/api/tests/integration/test_admission_race.py`
- [ ] T047 [P] [US2] Money test: running cost versus balance plus grace returns `end_call` with `insufficient_credit` at the right threshold in `services/api/tests/unit/test_credit_guard.py`
- [ ] T048 [P] [US2] Unit tests for every allowed and forbidden call transition and first-writer-wins disconnect reason in `services/api/tests/unit/test_call_state_machine.py`
- [x] T049 [P] [US2] Timer unit tests (inactivity reset rules, duration, simultaneous fire) in `services/voice-worker/tests/unit/test_timers.py` and harness scripts `services/voice-worker/tests/harness/scripts/inactivity.yaml`, `services/voice-worker/tests/harness/scripts/max_duration.yaml`
- [ ] T050 [P] [US2] Integration test for the reaper (queued past 60 s, heartbeat lost past 60 s, room deleted, slot released) in `services/api/tests/integration/test_reaper.py`

### Implementation for User Story 2

- [ ] T051 [US2] Add admission checks in order (email verified, version, vendors in `catalog.json`, pricing coverage via 001, balance above zero, advisory lock and active-call count) and refusal records to `admit()` in `services/api/app/calls/service.py`
- [ ] T052 [US2] Map refusals to problem types 402, 403, 409, 422, 429 with `call_id` in `services/api/app/sessions/router.py`
- [ ] T053 [US2] Implement mid-call credit guard on each events post using 001's running-cost estimate and `CREDIT_GRACE_USD` in `services/api/app/call_events/service.py`
- [x] T054 [US2] Implement `InactivityTimer` and `DurationTimer` on the session clock in `services/voice-worker/worker/call_behavior.py` and wire them in `services/voice-worker/worker/entry.py`
- [x] T055 [US2] Implement `CallControl.hang_up(reason)` (first writer wins, final status event, room delete) and handling of `control.end_call` responses in `services/voice-worker/worker/entry.py`
- [x] T056 [US2] Handle vendor stream failures (adapter retry window 5 s, then end with `error` and `vendor_error:<kind>/<provider>` diagnostic) in `services/voice-worker/worker/pipeline.py`
- [ ] T057 [US2] Implement `reap_stuck_calls` cron (15 s) in `services/api/app/calls/jobs.py`
- [ ] T058 [US2] Show refusal reasons and an "Add funds" link in `apps/web/src/routes/agents/components/WebCallPanel.tsx`

**Checkpoint**: No call starts or runs outside its limits.

---

## Phase 5: User Story 3 - The agent sounds and behaves the way it was configured (Priority: P1)

**Goal**: Turn-taking mapping, turn detection choice, pronunciation, background audio, all
vendor adapters.

**Independent Test**: Responsiveness 0.2 versus 0.9 on the same harness script yields a longer
reply wait for 0.2; pronunciation changes speech, not transcript.

### Tests for User Story 3 (write first, must fail)

- [x] T059 [P] [US3] Unit tests for interruption and responsiveness mapping (formulas, monotonicity, s = 0 disables) and turn detection selection in `services/voice-worker/tests/unit/test_turn_mapping.py`
- [x] T060 [P] [US3] Unit tests for the streaming pronunciation transform (whole word, case-insensitive, chunk boundaries, "MySQL" untouched) in `services/voice-worker/tests/unit/test_pronunciation.py`
- [x] T061 [P] [US3] Unit tests: every `catalog.json` entry builds through the registry with fake credentials; unknown provider raises in `services/voice-worker/tests/unit/test_registry.py`
- [x] T062 [P] [US3] Harness scenarios `interruption.yaml`, `responsiveness.yaml`, `pronunciation.yaml`, `background_audio.yaml` in `services/voice-worker/tests/harness/scripts/`

### Implementation for User Story 3

- [x] T063 [US3] Implement turn-taking mapping functions and turn detection selection (STT built-in versus semantic model, `multi` language) in `services/voice-worker/worker/pipeline.py`
- [x] T064 [US3] Implement the pronunciation streaming transform and wire it into the agent TTS node in `services/voice-worker/worker/audio.py`
- [x] T065 [US3] Implement background audio (built-in clips, uploaded file download and cache, gain clamp, missing-file warning) in `services/voice-worker/worker/audio.py`
- [ ] T066 [US3] Add signed `background_audio_url` to the claim RuntimeConfig in `services/api/app/calls/service.py`
- [x] T067 [US3] Truncate interrupted agent turns to played text and set `interrupted` in transcript items in `services/voice-worker/worker/metrics.py`
- [x] T068 [P] [US3] AssemblyAI and Sarvam STT adapters in `services/voice-worker/worker/adapters/stt/assemblyai.py` and `services/voice-worker/worker/adapters/stt/sarvam.py`
- [ ] T069 [P] [US3] (Deferred: not in the launch catalog, 002 data-model section 8.2) Anthropic LLM adapter in `services/voice-worker/worker/adapters/llm/anthropic.py`, built only when a catalog entry and a pricing row are added
- [x] T070 [P] [US3] Cartesia TTS adapter in `services/voice-worker/worker/adapters/tts/cartesia.py` (Sarvam TTS is not in the launch catalog; research R8)
- [x] T071 [P] [US3] Fish Audio streaming TTS adapter with character metering in `services/voice-worker/worker/adapters/tts/fishaudio.py`
- [x] T072 [P] [US3] ai-coustics NC adapter in `services/voice-worker/worker/adapters/nc/ai_coustics.py`
- [ ] T116 [US3] Auto speech recognition (FR-045): call 002's `voices.service.resolve_auto_stt` in `claim()` and put `stt_resolved_model` in RuntimeConfig (`services/api/app/calls/service.py`); the worker builds STT with the resolved id and reports it in usage meters (`services/voice-worker/worker/pipeline.py`, `metrics.py`); admission refuses a language the provider's Auto cannot cover; tests in `services/api/tests/unit/test_auto_stt.py` (Deepgram `en-US` to `nova-3`, `hi` to `nova-2`; AssemblyAI `es` to multilingual; Sarvam to `saarika:v2.5`) and a pricing check that a Deepgram Auto call in Hindi is charged at 0.0058 per minute
- [x] T117 [US3] Segment overrides (FR-046): `CallControl.apply_overrides()` in `services/voice-worker/worker/tools/__init__.py` (protocol) and `services/voice-worker/worker/pipeline.py` (swap LLM, TTS and STT at the next turn boundary, re-resolve Auto for a new language, clamp to RuntimeConfig `controls`, emit `segment_override` and `override_clamped` events, meter per model); harness scenario `services/voice-worker/tests/harness/scripts/segment_override.yaml` asserting the swap, clamping, per-model meters and first-turn latency after a swap within budget

**Checkpoint**: All builder settings change runtime behaviour; every listed vendor runs.

---

## Phase 6: User Story 4 - Every finished call is recorded, priced and processed in order (Priority: P2)

**Goal**: Ordered, idempotent post-call pipeline and dual-channel recording (skipped, with transcripts and metrics kept, when the call's recording setting is off).

**Independent Test**: Replay every step twice for an ended call: one charge, one notify step
completion, status `completed`, recording `available`.

### Tests for User Story 4 (write first, must fail)

- [ ] T073 [P] [US4] Contract test for `POST /v1/livekit/webhook` against `contracts/livekit_hooks.yaml` in `services/api/tests/contract/test_livekit_hooks_contract.py`
- [ ] T074 [P] [US4] Unit tests for the step runner (fixed order, blocking steps stop the chain, non-blocking failures recorded, unregistered handlers skipped, never-connected calls skip charge) in `services/api/tests/unit/test_pipeline_runner.py`
- [ ] T075 [P] [US4] Money test: replaying every step twice for 100 calls creates exactly one `call_charge` per call and one `notify_analyzed` completion in `services/api/tests/integration/test_pipeline_idempotency.py`
- [ ] T076 [P] [US4] Integration test: `egress_ended` sets recording status and key; `room_finished` closes an open call with `error` in `services/api/tests/integration/test_livekit_hooks.py`
- [ ] T111 [P] [US4] Unit tests for recording setting resolution at admission (workspace default on/off times agent override `inherit`/`on`/`off`, missing override reads as `inherit`, `recording_setting_source`, initial `recording_status`, values unchanged when either setting changes after admission) in `services/api/tests/unit/test_recording_setting.py`
- [ ] T112 [P] [US4] Integration test: call with recording off starts no egress, keeps `recording_status = not_recorded` even if an egress webhook arrives, still stores transcript, `turn` events, usage and `latency_stats`, is charged and `completed` with no pipeline warning, and `recording_state()` returns `not_recorded` with a null URL in `services/api/tests/integration/test_recording_disabled.py`

### Implementation for User Story 4

- [ ] T077 [US4] Implement the step table runner and handler registration for 007 (`register_step_handler("analyze" | "evaluate", fn)`) in `services/api/app/calls/pipeline.py`
- [ ] T078 [US4] Implement `finalize_transcript` (ordered items from `call_events`, `latency_stats` p50/p95/avg) in `services/api/app/calls/pipeline.py`
- [ ] T079 [US4] Implement `price_and_charge` calling 001 pricing and ledger with idempotency key `call_charge:{call_id}` in `services/api/app/calls/pipeline.py`
- [ ] T080 [US4] Implement `complete` (to `completed` or `voicemail`), `run_pipeline` job, and enqueue on `ended` in `services/api/app/calls/jobs.py` and `services/api/app/call_events/service.py`
- [ ] T081 [US4] Implement `start_recording` job at claim (audio-only, dual-channel agent mixing, MP4/AAC, SSE-KMS key `recordings/{workspace_id}/{call_id}.mp4`) in `services/api/app/calls/jobs.py`
- [ ] T082 [US4] Implement LiveKit webhook verification and handlers (`egress_started`, `egress_ended`, `room_finished`) in `services/api/app/livekit_hooks/router.py` and `services/api/app/livekit_hooks/service.py`
- [ ] T083 [US4] Add the `replay <call_id>` command and blocked-pipeline alert (structured log, OTel event, counter) in `services/api/app/calls/jobs.py`
- [ ] T113 [US4] Resolve the effective recording setting in `admit()` from the frozen version's `advanced.recording` (002) and `workspaces.recording_default` (001), write `recording_enabled`, `recording_setting_source` and initial `recording_status` (`none` or `not_recorded`), and add `recording_enabled` to the claim RuntimeConfig in `services/api/app/calls/service.py`
- [ ] T114 [US4] Skip egress in `start_recording` when `recording_enabled` is false, ignore egress webhooks for such calls, and implement `recording_state(call) -> CallRecordingState` for 006's recording URL endpoints in `services/api/app/calls/jobs.py`, `services/api/app/livekit_hooks/service.py` and `services/api/app/calls/service.py`

**Checkpoint**: Calls are billed once and fully processed.

---

## Phase 7: User Story 5 - Customers receive signed call events (Priority: P2)

**Goal**: Signed `call_started`, `call_ended`, `call_analyzed`; retries; delivery log; test
event; SSRF guard.

**Independent Test**: Endpoint failing twice then succeeding shows three attempts for
`call_analyzed`, the last succeeded, all signatures verify.

### Tests for User Story 5 (write first, must fail)

- [ ] T084 [P] [US5] Contract test for `/v1/webhooks/*` and the `webhooks` payload schemas against `contracts/webhooks_out.yaml` in `services/api/tests/contract/test_webhooks_out_contract.py`
- [ ] T085 [P] [US5] Unit tests for signing (fixed test vector, dual signature during rotation, 300 s tolerance) in `services/api/tests/unit/test_signing.py`
- [ ] T086 [P] [US5] Unit tests for the URL guard (RFC 1918, loopback, link-local, CGNAT, metadata IP, IPv6 equivalents, DNS rebinding, no redirects, HTTPS rule) in `services/api/tests/unit/test_url_guard.py`
- [ ] T087 [P] [US5] Integration test for retry schedule, non-retryable 400 and 410, timeout handling and manual redeliver in `services/api/tests/integration/test_webhook_retries.py` using `services/api/tests/integration/tools/flaky_receiver.py`

### Implementation for User Story 5

- [ ] T088 [P] [US5] Implement `sign()` and `verify()` in `services/api/app/webhooks_out/signing.py`
- [ ] T089 [P] [US5] Implement the SSRF guard and pinned-IP HTTP transport in `services/api/app/core/url_guard.py`
- [ ] T090 [US5] Implement secret lifecycle (lazy create, rotate with 24 h overlap, masking), envelope builder and idempotent enqueue per (call, event) in `services/api/app/webhooks_out/service.py` and `services/api/app/webhooks_out/schemas.py`
- [ ] T091 [US5] Implement the delivery job (timeout from version, attempts log, retry schedule with jitter) and 30-day purge cron in `services/api/app/webhooks_out/jobs.py`
- [ ] T092 [US5] Implement signing-secret, deliveries, redeliver and test endpoints in `services/api/app/webhooks_out/router.py`
- [ ] T093 [US5] Enqueue `call_started` and `call_ended` on transitions in `services/api/app/call_events/service.py` and implement the `notify_analyzed` step in `services/api/app/calls/pipeline.py`
- [ ] T115 [US5] Add `recording_enabled` and `recording_status` to the `WebhookCall` payload builder, with `recording_url` always null for `not_recorded` calls, in `services/api/app/webhooks_out/service.py` (covered by T084)

**Checkpoint**: Integrations receive verifiable events.

---

## Phase 8: User Story 6 - Voicemail and keypad input (Priority: P2)

**Goal**: Voicemail detection with hang up or leave message; keypad digits as caller turns.

**Independent Test**: Harness machine greeting plus beep leads to the message after the beep and
`voicemail_reached`; "1234#" becomes one caller turn.

### Tests for User Story 6 (write first, must fail)

- [x] T094 [P] [US6] Unit tests for the DTMF collector (termination key, digit limit, pause timeout, digits during agent speech) in `services/voice-worker/tests/unit/test_dtmf_collector.py`
- [x] T095 [P] [US6] Harness scenarios `voicemail_hangup.yaml`, `voicemail_leave_message.yaml`, `dtmf.yaml` in `services/voice-worker/tests/harness/scripts/`

### Implementation for User Story 6

- [x] T096 [US6] Implement `DtmfCollector` and wire `sip_dtmf_received` to a single keypad caller turn plus `dtmf` events in `services/voice-worker/worker/call_behavior.py`
- [x] T097 [US6] Implement `CallControl.send_dtmf()` for 005's press-digit tool in `services/voice-worker/worker/entry.py`
- [x] T098 [US6] Implement voicemail detection for outbound calls (internal tool for the first 30 s, hang-up and leave-message actions, post-greeting silence wait) in `services/voice-worker/worker/call_behavior.py`
- [ ] T099 [P] [US6] Add a keypad to the test panel that publishes DTMF in `apps/web/src/routes/agents/components/Keypad.tsx`

**Checkpoint**: Outbound-ready behaviours verified offline.

---

## Phase 9: User Story 7 - Test the runtime without phones or vendors (Priority: P3)

**Goal**: Script authoring for any agent version, CI suite under 5 minutes, latency benchmark gate.

**Independent Test**: Harness suite passes offline under 5 minutes; benchmark reports p50/p95
against baseline.

- [x] T100 [P] [US7] Add a CLI to run one script against an exported agent version JSON (`python -m tests.harness.runner --config ... --script ...`) in `services/voice-worker/tests/harness/runner.py`
- [x] T101 [P] [US7] Document the script format and fakes in `services/voice-worker/tests/harness/README.md`
- [x] T102 [US7] Implement the benchmark synthetic caller (WAV playback, agent audio onset detection, per-turn e2e) and the 20 x 6 call set in `services/voice-worker/tests/harness/benchmark.py`, `services/voice-worker/tests/harness/benchmarks/callset.yaml` and `services/voice-worker/tests/harness/benchmarks/fixtures/`
  - Built as `tests/harness/bench/` (`benchmark.py --mode live`, `live.py`, `live_fakes.py`, `synth.py`, `callset.yaml`, `fixtures/turn_<n>.wav`, `baseline_live.json`): real WebRTC rooms on `livekit-server --dev`, the production agent server and job entry, caller-side `e2e_ms`. Vendors are fakes with the call set's delay profiles (no keys); a real-vendor run needs the default-stack keys and intelligible fixtures (see `tests/harness/README.md`). First live baseline fails the budget (p50 953 ms, p95 2,734 ms): Silero end of speech bounds end of turn at about 600 ms, and a digit-string turn waits the full 2.4 s semantic max delay. Input for the R4 calibration and for T105.
- [x] T103 [US7] Implement baseline comparison (p50 at most 800 ms, p95 at most 1,500 ms, no more than 10% regression) and baseline refresh command writing `services/voice-worker/tests/harness/benchmarks/baseline.json`
- [ ] T104 [US7] Add a CI time budget assertion (harness job fails above 5 minutes) to `.github/workflows/voice-worker.yml`
- [ ] T105 [US7] Latency budget gate (Principle II): add `.github/workflows/voice-benchmark.yml` running T102 nightly and on PRs touching `services/voice-worker/worker/**`, publishing p50/p95 and blocking merge on failure; commit the first baseline from the default stack

**Checkpoint**: Hot-path regressions are caught before merge.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [x] T106 [P] Add OpenTelemetry spans (`call`, per-turn, claim, events post, pipeline steps) with `call_id` attribute in `services/voice-worker/worker/entry.py`, `services/voice-worker/worker/metrics.py` and `services/api/app/calls/pipeline.py`
  - Worker side done in `services/voice-worker/worker/telemetry.py` (exporter from `CALLWRIGHT_OTEL_EXPORTER`, no-op by default; tests in `tests/unit/test_telemetry.py`). The pipeline-step spans in `services/api/app/calls/pipeline.py` belong with T077 in the API wave.
- [ ] T107 [P] RLS isolation tests for all 003 tables (cross-workspace reads and internal endpoint workspace derivation) in `services/api/tests/integration/test_rls_voice_runtime.py`
- [ ] T108 [P] Events ingest performance check (p95 under 50 ms for 50-event batches) in `services/api/tests/integration/test_events_ingest_perf.py`
- [ ] T109 Security review of tokens, service token handling, webhook secret masking and URL guard; record findings in the PR
- [ ] T110 Run every section of `specs/003-voice-runtime/quickstart.md` and fix drift

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1) has no dependencies.
- Foundational (Phase 2) depends on Setup and blocks all stories.
- US1, US2, US3 (P1) start after Phase 2. US2 and US3 extend files touched in US1
  (`calls/service.py`, `worker/entry.py`, `worker/pipeline.py`), so run US1 first, then US2 and
  US3 in parallel by different people on different files where marked [P].
- US4 depends on US1 (call ends). US5 depends on US4 for `notify_analyzed` (T093) but T084 to
  T092 can start after US1. US6 depends on US1 and US2 (`CallControl`, timers).
- US7 depends on US1 for a working pipeline. **The benchmark gate (T102, T103, T105) must be
  merged before any US3 or later change to `services/voice-worker/worker/**` lands on main**,
  so the Principle II gate is active for every hot-path change after the MVP.
- Polish depends on the stories it touches.

### Cross-feature dependencies

- 001: balance, ledger charge with idempotency key, pricing estimate and running cost,
  concurrency limit, email-verified flag, `secrets` table, `core` package, and the workspace
  recording default `workspaces.recording_default` (boolean, default true, editable in 001's
  workspace settings) read by T113.
- 002: `AgentConfig` schema, `agent_versions.service.snapshot_for_test()`, published version
  lookup, and the agent recording override `AgentConfig.advanced.recording` (`inherit`, `on`,
  `off`, default `inherit`) read by T113.
- 006: its recording URL endpoints use `recording_state()` (T114) and show "not recorded".
- Provides to 004, 005, 007, 010: the extension points listed in plan.md.
- Spec FR-017 (inbound ring duration) and SIP dialling are delivered by 010 in
  `services/voice-worker/worker/telephony.py` (010 T020, T033), since only phone and WhatsApp
  calls ring.

### Within Each User Story

- Tests first and failing; models before services; services before routers; API before web.

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "T021 Contract test sessions in services/api/tests/contract/test_sessions_contract.py"
Task: "T022 Contract test claim in services/api/tests/contract/test_calls_internal_contract.py"
Task: "T023 Contract test events in services/api/tests/contract/test_call_events_contract.py"
Task: "T025 Usage snapshot money test in services/api/tests/unit/test_usage_snapshot.py"
Task: "T026 Billable seconds money test in services/api/tests/unit/test_billable_seconds.py"

# Default-stack adapters together:
Task: "T034 Deepgram STT adapter"   Task: "T035 OpenAI/Azure LLM adapters"
Task: "T036 ElevenLabs TTS adapter" Task: "T037 Sanas/none NC adapters"
```

## Implementation Strategy

### MVP First

1. Phase 1 and Phase 2.
2. US1: browser test call on the default stack. Validate with quickstart section 3.
3. US2 immediately after (calls must not run unpaid or unbounded before any external user).
4. US7 benchmark tasks T102, T103, T105 next, to arm the latency gate.

### Incremental Delivery

US3 (all vendors and behaviours), then US4 (billing correct), US5 (integrations), US6
(outbound readiness for 010), each validated with its quickstart section.
