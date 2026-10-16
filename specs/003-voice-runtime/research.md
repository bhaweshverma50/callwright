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

- **Decision**: Pure functions in `worker/call_behavior.py` (the only place to change the
  calibration), unit-tested, mapping the two 0..1 values to `AgentSession` turn handling
  (`turn_handling_options` in `worker/pipeline.py`). Calibrated v2 (2026-10-16) against the
  live WebRTC benchmark (T102) and the pause scenarios below:

  | Input | Parameter | Formula | At default |
  |---|---|---|---|
  | interruption_sensitivity `s` | `interruption.enabled` | `s > 0` | true (s = 0.9) |
  | | `interruption.min_duration` (s) | `0.2 + (1 - s) * 0.6` | 0.26 s |
  | | `interruption.min_words` | `0 if s >= 0.7 else (1 if s >= 0.3 else 2)` | 0 |
  | | `interruption.false_interruption_timeout` (s) | fixed `1.0` | 1.0 s |
  | | `interruption.resume_false_interruption` | fixed `true` | true |
  | responsiveness `r` | `endpointing.min_delay` (s) | `0.3 + (1 - r) * 0.5` | 0.40 s |
  | | `endpointing.max_delay` (s) | `0.9 + (1 - r) * 1.6` | 1.22 s |
  | | `endpointing.mode` | fixed `"fixed"` | |
  | fixed | Silero VAD `min_silence_duration` (s) | `0.3` | 0.3 s |
  | fixed | `preemptive_generation` | `{enabled: true, preemptive_tts: true}` | |
  | fixed | caller audio `frame_size_ms` | `20` | 20 ms |
  | fixed | digit-string rule | trailing digit string is unfinished | |

  When the STT model supplies its own turn detection (R5), only `min_delay` applies.

- **How a turn ends** (livekit-agents 1.8.8, `audio_recognition.py`): Silero reports end of
  speech after `min_silence_duration` of silence; the semantic model then scores the transcript,
  and the turn commits `min_delay` after the last speech if the model reads the caller as done,
  or `max_delay` after it if the probability is under the model's per-language unlikely
  threshold. Speech that resumes inside the wait cancels it. So a finished turn waits
  `max(vad_silence, min_delay)` and `max_delay` is the longest mid-sentence pause the agent sits
  through. Preemptive generation starts the LLM (and, with `preemptive_tts`, the TTS) on each
  final transcript, so when the wait is shorter than STT final + LLM first token + TTS first
  byte the reply is ready at commit time.

- **Rationale, from the measurements**:
  - v1 (`0.2 + (1 - r) * 1.0`, `1.5 + (1 - r) * 4.5`, VAD default 0.55 s) measured p50 953 ms
    and p95 2,734 ms at the caller. End of turn sat at about 610 ms because the VAD window, not
    `min_delay`, was the floor (the offline model assumed 0.4 s), and the digit turn ("four four
    one nine") always waited the 2.45 s max delay, which set p95.
  - VAD silence 0.3 s makes `min_delay` the real knob again. It stays above the 0.25 s the
    framework requires for the audio turn detector, and the lowest `min_delay` equals it, so no
    responsiveness value is a dead zone. 0.40 s at the default sits between the framework's
    0.3 s (audio detector) and 0.5 s (text detector) defaults. With it, five of six turns in the
    call set are bound by the vendor chain, not by endpointing (end of turn 400 ms, reply ready
    at about 520 to 620 ms in the worker).
  - `max_delay` is a correctness parameter, not a speed one: it must outlast the pauses callers
    make inside a sentence and between digit groups (0.6 to 1.0 s in the scenarios below) and
    still keep an unfinished-looking turn under the 1,500 ms p95 at the caller, which adds about
    180 ms of WebRTC transport. 1.22 s does both (digit turns measure 1.39 to 1.41 s at the
    caller). The range runs from 0.9 s (r = 1, still above a 700 ms digit-group pause) to 2.5 s
    (r = 0, the framework ceiling). `max_delay - min_delay >= 0.5 s` everywhere.
  - Preemptive TTS takes the TTS first byte off every turn that waits `max_delay` (the reply is
    synthesized during the wait). Cost: a preemptive attempt that the caller's next words
    supersede has its characters synthesized and metered (R7) without being played; at most
    `max_retries` (3) attempts per turn.
  - Digit strings: the multilingual model held "the account number is four four one nine" but
    scored "my account number is four four one" as finished, so with only the mapping the agent
    took the turn in the 700 ms pause before the next group in 8 of 8 live calls.
    `worker/turn_detection.py` wraps the model: a transcript ending in a run of two or more
    number words or a multi-digit numeral (and not a question) is unfinished and waits
    `max_delay`; everything else is the model's decision.
  - False interruptions: a barge-in with no transcript resumes the agent after 1.0 s instead of
    the framework's 2.0 s. Streaming STT finals land within about 0.5 s of end of speech, so a
    real short interruption still produces a transcript first, and a cough stops the agent for
    half as long.
  - 20 ms input frames (framework default 50 ms) cut the average framing delay before VAD and
    STT hear the end of speech by about 15 ms.
  - Endpointing stays `fixed`: the dynamic mode only lengthens `min_delay` after the caller has
    already paused through it, and makes the builder value harder to explain.
  - Turn detector: the multilingual model for every language (R5). It strips punctuation before
    scoring, so a streaming STT full stop on a fragment does not read as finished; the English
    model scores raw text.

- **Evidence** (`tests/harness/bench`, local `livekit-server --dev`, fake vendors on the call
  set's profiles, 20 x 6 calls, 4 concurrent):

  | | p50 caller | p95 caller | end of turn (median) | worker p50 |
  |---|---|---|---|---|
  | v1 | 953 ms | 2,734 ms | 608 ms | 765 ms |
  | v2 | 770 ms | 1,402 ms | 400 ms | 597 ms |

  Pause scenarios (`callset_pauses.yaml`, 8 x 6 calls: pauses of 0.6 to 1.0 s after "I would
  like to", "the new address is", "I was born on", "can you also tell me" and between digit
  groups): 0 cut-offs, p95 1,427 ms. Offline (`digit_groups.yaml`, `mid_sentence_pause.yaml`,
  `test_scenarios.py`) the same holds and the boundary is pinned: a 1.4 s mid-sentence pause and
  a pause after a sentence that sounds finished ("I paid. | The rest comes Friday.") end the
  turn, and the rest of the sentence barges in on the reply.

- **Floor**: with the call set's vendor medians (STT final 160 ms, LLM first token 320 ms, TTS
  first byte 130 ms) and about 180 ms of transport between the caller and the worker, a finished
  turn cannot reach the caller much before 700 ms; the measured p50 of 770 ms is that floor plus
  log-normal spread, and run-to-run variation is about 30 ms, so p50 has little margin against
  800 ms. Further p50 gains have to come from the vendors (STT finals, LLM first token,
  streaming TTS) or a lower `min_delay`, which would cut callers off sooner. p95 is set by
  `max_delay` plus transport.

- **Alternatives**: Exposing raw framework parameters in the builder (rejected: couples config
  schema to one framework, Principle I). Step tables with three levels (rejected: the builder
  sliders are continuous). Lowering the model's unlikely threshold (rejected: it is tuned per
  language for accuracy and would cut more unfinished sentences). Dynamic endpointing
  (rejected, above). A shorter `max_delay` for more p95 margin (rejected: the digit-group and
  hesitation pauses need it).

## R5. Turn detection

- **Decision**: `turn_detection="stt"` when the selected STT model declares built-in end of turn
  (registry capability flag; today Deepgram `flux-general-en` and AssemblyAI
  `universal-streaming*`). Otherwise the LiveKit multilingual turn-detector model with Silero VAD
  for every language, including `multi`, wrapped by the digit-string rule (R4).
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
  Initial set (matches 002's launch catalog): STT `deepgram`, `assemblyai`, `sarvam`; LLM
  `openai`, `azure_openai`; TTS `elevenlabs`, `cartesia`, `fishaudio`; NC `sanas` (models `vi`
  voice isolation and `st` standard), `ai_coustics` (model `standard`), and the internal
  passthrough `none` used when the config is `null`. Sarvam TTS is not offered at launch (no price
  row, ElevenLabs covers the Indic languages); Anthropic stays an API-side gateway option (002)
  and is not a call-time vendor. Vendors with a maintained LiveKit plugin wrap it; Fish Audio and Sanas
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

## R22. Auto speech recognition and segment overrides (live UI findings, 2026-10-16)

- **Decision**: Auto (`stt.model = null`) is resolved once per call, at claim, by 002's
  `voices.service.resolve_auto_stt(provider, language)` using the catalog `auto_rule`
  (Deepgram: `nova-3` for English variants, `nova-2` otherwise; AssemblyAI:
  `universal-streaming` for English, `universal-streaming-multilingual` for es, fr, de, it, pt;
  Sarvam: `saarika:v2.5`). The resolved id goes into RuntimeConfig and usage meters, so 001 prices
  the model actually used (the reference priced Deepgram Auto at the Nova-3 rate even when it ran
  Nova-2 for other languages).
- **Decision**: The worker exposes `CallControl.apply_overrides(overrides)` to the FlowRunner
  (004): it swaps the LLM, the TTS stream (provider, model, voice, speed, expressiveness, volume)
  and the STT stream (provider, model, language, re-resolving Auto) at the next turn boundary,
  clamps values to the shared `controls` table, emits `segment_override` or `override_clamped`
  system events, and keys usage meters by model. Swaps happen between turns, never mid-utterance.
- **Decision**: Browser test calls request microphone permission in the test panel before
  calling `POST /v1/sessions/web-call`; a denial never reaches the API. The same rule is offered to
  006 for the voice copilot (the reference showed only a toast on hold-to-talk and minted its token
  on every page load).
- **Rationale**: Exact pricing, one range table across agent and node settings, and no billed or
  counted calls for a browser that cannot send audio.
- **Latency (Principle II)**: STT swaps reconnect a stream at a turn boundary; T117 adds a harness
  scenario that asserts the first turn after a swap stays inside the p95 budget.

