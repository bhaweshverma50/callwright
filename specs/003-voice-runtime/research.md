# Research: Voice Runtime

**Feature**: 003-voice-runtime | **Date**: 2026-10-16 | **Plan**: [plan.md](./plan.md)

Each entry records a decision, why it was made, and what was rejected. Items marked "verify at
implementation" are framework facts to confirm against the pinned library version during the
first task that touches them; none changes the design if it turns out differently.

## R1. Runtime framework and dispatch

- **Decision**: LiveKit Agents for Python (1.x line, `AgentSession` API) in
  `services/voice-worker`. Workers register with an explicit `agent_name="callwright-voice"` so
  they join only rooms they are dispatched to. Each dispatch carries JSON metadata
  `{"call_id": "call_..."}` for calls the API created (web, outbound) or
  `{"channel": "sip_inbound" | "whatsapp", "route_ref": "..."}` for calls created by a SIP
  dispatch rule (feature 010). Heavy models (Silero VAD, the turn-detector model) load once per
  process in `prewarm`.
- **Rationale**: Mandated by the constitution; explicit dispatch prevents workers joining
  unrelated rooms and gives one place to pass the call identity.
- **Alternatives**: Automatic dispatch to every room (rejected: egress and future non-call rooms
  would get an agent). A custom media server (rejected: Principle VI).

## R2. Call identity, claim and admission

- **Decision**: One admission function, `calls.service.admit()`, used by every channel. Web and
  outbound calls are admitted by the API before the room exists (the room is created only for an
  admitted call). Inbound SIP and WhatsApp calls are admitted when the worker starts its job: the
  worker calls `POST /v1/internal/calls/claim` with the dispatch metadata and SIP participant
  attributes; the API routes the call (010's inbound router), admits it, creates the call row and
  returns the frozen configuration. For pre-admitted calls the same endpoint just returns the
  configuration and marks the call claimed. Refused inbound calls return `admitted: false` with
  the reason; the worker hangs up without speaking.
- **Rationale**: A single claim path means the worker has one startup sequence for all channels,
  and the API stays the only writer of call state and the only holder of database credentials.
- **Alternatives**: Admission inside the worker with direct database access (rejected: spreads
  RLS-sensitive writes across deployables). Admission in a LiveKit webhook (rejected: webhooks
  can arrive after the worker has already joined).

## R3. Concurrency and credit checks

- **Decision**: Inside the admission transaction: `SELECT pg_advisory_xact_lock(hashtext(workspace_id))`,
  then count calls in `queued`, `ringing` or `in_progress` for the workspace (partial index), then
  compare with `workspaces.concurrency_limit`, then read the derived balance from 001's billing
  service, then insert the call. Balance must be strictly above zero (001 FR-015). Mid-call, every
  `POST /v1/internal/calls/{id}/events` call recomputes the running cost estimate using 001's
  pricing service on the latest cumulative usage meters and elapsed connected time; when
  `balance - running_cost < -grace` (grace from 001 config, default $0.50) the response carries
  `control.action = "end_call"` with reason `insufficient_credit`. The worker posts at least every
  10 seconds (heartbeat), so the check runs at least every 15 seconds as FR-025 requires.
- **Rationale**: A transaction-scoped advisory lock serialises admissions per workspace without a
  new component; counting rows keeps one source of truth (no counter to drift). Piggybacking the
  credit check on events avoids a second channel from API to worker.
- **Alternatives**: Redis counters for slots (rejected: drift after crashes needs reconciliation
  anyway). Reserving credit up front for the maximum duration (rejected: blocks legitimate calls
  on small balances; can be added later as a policy).

## R4. Interruption sensitivity and responsiveness mapping

- **Decision**: Pure functions in `worker/pipeline.py`, unit-tested, mapping the two 0..1 values
  to `AgentSession` turn parameters. Initial calibration (tuned later with the benchmark set; the
  table is the only place to change):

  | Input | Parameter | Formula | At default |
  |---|---|---|---|
  | interruption_sensitivity `s` | `allow_interruptions` | `s > 0` | true (s = 0.95) |
  | | `min_interruption_duration` (s) | `0.2 + (1 - s) * 0.6` | 0.23 s |
  | | `min_interruption_words` | `0 if s >= 0.7 else (1 if s >= 0.3 else 2)` | 0 |
  | responsiveness `r` | `min_endpointing_delay` (s) | `0.2 + (1 - r) * 1.0` | 0.41 s |
  | | `max_endpointing_delay` (s) | `1.5 + (1 - r) * 4.5` | 2.45 s |

  When the STT model supplies its own turn detection (R5), only `min_endpointing_delay` applies.
- **Rationale**: Monotonic, simple to explain in the builder ("higher is faster"), and the
  midpoints (s = 0.5, r = 0.5) land on the framework defaults (0.5 s interruption, about 0.7 s
  endpointing), so behaviour is familiar.
- **Alternatives**: Exposing raw framework parameters in the builder (rejected: couples config
  schema to one framework, Principle I). Step tables with three levels (rejected: the builder
  sliders are continuous).

## R5. Turn detection

- **Decision**: `turn_detection="stt"` when the selected STT model declares built-in end of turn
  (registry capability flag; today Deepgram `flux-general-en` and AssemblyAI
  `universal-streaming*`). Otherwise the LiveKit multilingual turn-detector model with Silero VAD.
  Language `multi` uses the multilingual model.
- **Rationale**: Built-in STT turn signals are lower latency and avoid running a second model;
  the semantic model cuts false end-of-turn on pauses compared with VAD alone.
- **Alternatives**: VAD-only endpointing (rejected: more false interruptions mid-sentence).

## R6. Latency measurement

- **Decision**: End-to-end per turn is measured directly in the worker: `e2e_ms` = timestamp of
  first agent audio frame played into the room minus the VAD end-of-speech timestamp of the
  caller turn that triggered it. Component metrics come from the framework's `metrics_collected`
  events: `stt_final_ms` (EOU metrics `transcription_delay`), `eou_delay_ms`
  (`end_of_utterance_delay`), `llm_ttft_ms` (LLM metrics `ttft`, first generation of the turn),
  `tts_ttfb_ms` (TTS metrics `ttfb`). Tool time inside a turn is reported separately as
  `tool_ms` by 005's hook. The opening line records `greeting_ms` from caller connection to first
  agent audio. Verify at implementation: field names in the pinned `livekit-agents` version.
- **Rationale**: Principle II defines latency as end of user speech to first agent audio; the
  direct measurement is authoritative and the components explain it.
- **Alternatives**: Summing component metrics only (rejected: hides queueing and playout delays).

## R7. Usage meters

- **Decision**: The worker keeps cumulative counters per (component, provider, model):
  `stt.audio_ms`, `llm.input_tokens`, `llm.cached_input_tokens`, `llm.output_tokens`,
  `tts.characters`, `nc.audio_ms`. It posts the full cumulative snapshot in a `usage` event with
  every batch; the API stores the latest snapshot by sequence number (last write wins). Pricing
  (001) reads the final snapshot. Characters counted are those actually sent to TTS (after
  pronunciation replacement), including the greeting and voicemail message.
- **Rationale**: Cumulative snapshots make retries and duplicate posts harmless and need no
  summation logic on the server.
- **Alternatives**: Per-turn deltas summed on the server (rejected: lost or duplicated batches
  corrupt totals).

## R8. Vendor adapters (Principle I)

- **Decision**: `worker/adapters/{stt,llm,tts,nc}/<vendor>.py`, each exposing
  `build(config, ctx) -> framework component` plus a `capabilities` record (streaming, built-in
  turn detection, supported languages, meter units). `worker/adapters/registry.py` maps
  `(kind, provider)` to the module; unknown pairs raise `UnsupportedVendor`. The API checks the
  same provider list (exported from the worker package as data, `adapters/catalog.json`) during
  admission so unsupported vendors are refused before a room exists.
  Initial set: STT `deepgram`, `assemblyai`, `sarvam`; LLM `openai`, `azure_openai`,
  `anthropic`; TTS `elevenlabs`, `cartesia`, `fishaudio`, `sarvam`; NC `sanas_vi`, `sanas_st`,
  `ai_coustics`, `none`. Vendors with a maintained LiveKit plugin wrap it; Fish Audio and Sanas
  are thin adapters over the vendor streaming APIs implementing the framework's TTS and audio
  filter interfaces. Verify at implementation: plugin availability for Fish Audio and
  ai-coustics.
- **Rationale**: One file per vendor keeps vendor changes local and reviewable; the catalog file
  avoids the API importing worker code.
- **Alternatives**: A generic HTTP adapter configured by data (rejected: vendor streaming
  protocols differ too much).

## R9. Silence and maximum duration

- **Decision**: An `InactivityTimer` in `worker/call_behavior.py` resets on caller VAD speech
  start, agent speech start, keypad digit, and while a reply is being generated or a tool is
  running; it fires after `end_on_silence_s`. A `DurationTimer` starts at connection and fires at
  `max_duration_s`; on fire the agent interrupts its own speech, the session closes and the room
  is deleted within 5 seconds. Both use the session's clock so the harness can drive them with a
  fake clock.
- **Rationale**: Matches the spec's definition of silence (neither party and no pending work).
- **Alternatives**: The framework's `user_away_timeout` alone (rejected: tracks only the user).

## R10. Voicemail detection

- **Decision**: For `sip_outbound` calls with detection on, for the first 30 seconds after
  answer the LLM gets an extra internal tool `report_answering_machine` and a short instruction
  to call it when the audio is a greeting or voicemail prompt. On detection: `end_call` action
  hangs up at once; `leave_message` waits until VAD reports 1.5 seconds of silence after the
  greeting (the beep is followed by silence), speaks the message through TTS without the LLM,
  then hangs up. Status `voicemail`, reason `voicemail_reached`.
- **Rationale**: Carrier-level answering machine detection is not uniformly available on BYO
  trunks; the LLM approach is the documented LiveKit pattern and works on any channel.
- **Alternatives**: Beep-frequency detection DSP (rejected for v1: brittle across carriers; can be
  added behind the same interface).

## R11. Keypad input (DTMF)

- **Decision**: SIP calls deliver digits as room `sip_dtmf_received` events; browser test calls
  send digits with the client's DTMF publish method, which arrives as the same event. A
  `DtmfCollector` buffers digits and flushes on termination key, digit count or pause, then
  injects one user turn `"<digits>"` marked `source: keypad`. Agent-side tone sending (IVR
  navigation) is exposed in `CallControl.send_dtmf()` for 005's press-digit tool.
- **Rationale**: One code path for both channels and testable without telephony.

## R12. Background audio and pronunciation

- **Decision**: Background audio uses the framework's `BackgroundAudioPlayer` with the built-in
  clip ids (`office_ambience`, `city_ambience`, `forest_ambience`, `crowded_room`, `hold_music`,
  `keyboard_typing`, `keyboard_typing2`). Uploaded files are referenced by object key; the claim
  response includes a 10-minute signed URL, the worker downloads and caches by key. Volume
  (builder range 0 to 3) is passed as the player's gain, clamped to 0..2 to avoid clipping.
  Pronunciation runs as a text transform in the
  agent's TTS node: a streaming whole-word, case-insensitive replacer that holds back a partial
  trailing word until a boundary arrives, so replacements across chunk boundaries work. The
  transcript is taken from the LLM output before the transform.
- **Alternatives**: SSML phoneme tags (rejected: not supported by every TTS vendor).

## R13. Recording

- **Decision**: The API starts a LiveKit room-composite egress, audio only, with
  `DUAL_CHANNEL_AGENT` mixing (agent left, everyone else right), MP4 container with AAC audio, to
  the recordings bucket at `recordings/{workspace_id}/{call_id}.mp4` with SSE-KMS. It starts when
  the call is claimed (before the greeting), from an arq job so the claim response is not
  delayed. `egress_ended` from the LiveKit webhook sets `recording_status` to `available` or
  `failed`. Playback URLs are signed for 10 minutes by 006. When the call's
  `recording_enabled` (resolved at admission, spec FR-043) is false, the job is a no-op, no
  egress exists, and `recording_status` is `not_recorded`.
- **Rationale**: Keeps storage credentials out of the worker; dual channel lets evaluators and
  reviewers separate speakers; AAC plays in every target browser.
- **Alternatives**: Track egress per participant (rejected: two files to align). OGG/Opus
  (rejected: uneven browser support for download and playback).

## R14. Post-call pipeline orchestration

- **Decision**: `call_ended` (from the worker's final status event, or from the reaper) enqueues
  `run_pipeline(call_id)` on arq. A `call_pipeline_steps` row per (call_id, step) records state.
  Steps run in fixed order: `finalize_transcript`, `price_and_charge`, `analyze`, `evaluate`,
  `notify_analyzed`, `complete`. Each step: `SELECT ... FOR UPDATE SKIP LOCKED` on its row; if
  `done` or `skipped`, continue; else run and mark `done` in the same transaction as its writes.
  `price_and_charge` calls 001's charge with idempotency key `call_charge:{call_id}`. `analyze`
  and `evaluate` look up handlers registered by 007; with none registered they are `skipped`.
  Blocking steps retry with exponential backoff (5 attempts, 10 s base) then raise an alert;
  non-blocking steps are marked `failed` and the chain continues.
- **Rationale**: Architecture section 6 fixes the order and idempotency key; a step table makes
  retries and observability explicit without a workflow engine.
- **Alternatives**: Temporal or a workflow engine (rejected: Principle VI).

## R15. Customer webhooks

- **Decision**: Header `Callwright-Signature: t=<unix seconds>,v1=<hex>` where `v1` is
  HMAC-SHA256 over `"{t}.{raw_body}"` with the workspace secret (`whsec_` + 32 random bytes,
  base64url). During the 24-hour rotation overlap a second `v1=` value is appended. Extra headers:
  `Callwright-Event`, `Callwright-Delivery` (delivery id), `User-Agent: Callwright-Webhooks/1`.
  Delivery is an arq job; retries use `_defer_by` at 10 s, 60 s, 300 s, 1,800 s, 7,200 s with
  plus or minus 10% jitter. HTTP client: `httpx` with the per-agent timeout, redirects not
  followed. SSRF guard resolves the host, rejects private, loopback, link-local, CGNAT and
  metadata ranges, then connects to the resolved IP with the original Host and SNI.
- **Rationale**: The timestamped scheme is widely understood and protects against replay;
  not following redirects closes an SSRF bypass.
- **Alternatives**: Signing body only (rejected: replayable). JWT bodies (rejected: harder for
  customers to verify).

## R16. Reaper for stuck calls

- **Decision**: arq cron every 15 seconds: calls `queued` with no claim after 60 seconds become
  `failed` (diagnostic `worker_unavailable` or `caller_never_joined` for web); calls `ringing` or
  `in_progress` with `last_heartbeat_at` older than 60 seconds become `ended` with reason `error`,
  the room is deleted, and the pipeline is enqueued. The LiveKit `room_finished` webhook ends any
  still-open call for that room with `error` as a second safety net.

## R17. Browser client

- **Decision**: `livekit-client` only (no component library). The panel subscribes to the
  agent's audio, reads agent state from the agent participant attribute `lk.agent.state`, and
  builds the live transcript from the `lk.transcription` text stream topic. Keypad digits use
  the client's DTMF publish method. Token has grants: join one room, publish microphone only,
  publish data, subscribe; TTL 15 minutes; identity `web-{user_id}-{short}`.
- **Rationale**: Constitution names `livekit-client`; the needed UI is small.

## R18. Draft test calls

- **Decision**: `version: "draft"` calls 002's `agent_versions.service.snapshot_for_test(agent_id)`
  which returns an existing version when the draft's content hash matches, or creates an
  unpinned version marked `source: test`. Published pointer is untouched.
- **Rationale**: Keeps "every call references an immutable version" without forcing a publish.

## R19. Internal authentication

- **Decision**: Worker to API calls use `Authorization: Bearer <service token>` (static secret
  from the secret store, rotated by deploy), checked by `core.auth.require_service()`. Internal
  endpoints set the RLS workspace from the call row they touch, never from the request body.
  LiveKit webhooks are verified with the LiveKit `WebhookReceiver` (JWT signed with the API
  secret, body SHA-256 claim).

## R20. Offline harness and benchmark

- **Decision**: Two modes in `services/voice-worker/tests/harness/`.
  1. **Offline** (CI default): the real `AgentSession` and `call_behavior` code run against fake
     adapters (`FakeSTT` emits scripted transcripts with configured delays, `FakeLLM` returns
     scripted or rule-based replies and tool calls, `FakeTTS` produces silent frames with a
     configured first-byte delay) and a fake room transport driven by a virtual clock. Scripts
     are YAML: steps `say`, `interrupt_after_ms`, `silence_s`, `dtmf`, `machine_greeting`,
     `expect_agent_says`, `expect_tool`, `expect_transition`, `expect_end_reason`,
     `expect_within_ms`. No network, deterministic.
  2. **Benchmark**: a local `livekit-server --dev`, a synthetic caller participant that plays
     WAV fixtures and detects agent audio onset, and real vendor adapters on the default stack.
     20 calls x 6 turns. Outputs p50/p95 `e2e_ms` and component medians, compared with
     `benchmarks/baseline.json`; fails when p50 > 800 ms, p95 > 1,500 ms, or either regresses
     more than 10% versus baseline. Runs nightly and on PRs touching hot-path paths.
- **Rationale**: Principle VII requires an offline harness; Principle II requires a benchmark
  gate. Splitting them keeps CI fast and deterministic while measuring real latency where it
  matters.
- **Alternatives**: Only the framework's text-mode test helpers (rejected: cannot exercise
  timers, interruptions or keypad input).

## R21. Observability

- **Decision**: OpenTelemetry in both deployables; root span `call` with attribute `call_id`,
  child span per turn with the latency fields as attributes, and spans for claim, events posts
  and each pipeline step. Per-turn latency is also stored in `call_events` (Principle II).
