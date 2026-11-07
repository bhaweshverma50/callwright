# Callwright Architecture Conventions (HLD)

**Version 1.2** (2026-10-16). Shared by every spec and plan under `specs/`. Plans MUST use these
names, paths and patterns. Deviations go in the plan's Complexity Tracking table. Section 8 lists
what changed from 1.0 after the ten specs were written.

## 1. Runtime topology

```
                 +---------------------------- Browser (apps/web) ----------------------------+
                 | React SPA, TanStack Query, livekit-client (web test calls), STT stream for  |
                 | the voice copilot (short-lived vendor key)                                  |
                 +-------+-----------------------------+--------------------------------------+
                         | HTTPS /v1 (JWT)             | WebRTC (room token)
                         v                             v
 +----------------------------------+        +---------------------------+   SIP trunk   +------------+
 | services/api  (FastAPI)          |------> | LiveKit (Cloud/self-host) |<------------> | Carrier /  |
 |  REST + webhooks (Stripe, LK,    | rooms, |  rooms, SIP trunks,       |               | customer   |
 |  Meta), RLS-scoped DB sessions,  | trunks,|  dispatch rules, egress   |               | SIP trunk  |
 |  admission, egress, signed URLs  | tokens +----------+----------------+               +------------+
 +-------+--------------+-----------+                   | agent dispatch                 +------------+
         | enqueue      | SQL                           v                                | WhatsApp   |
         v              v                     +-----------------------------+  SIP mode | Cloud API  |
 +--------------+ +-----------------------+   | services/voice-worker       |<--------->| Calling    |
 | Redis (arq)  | | Postgres 16           |<--|  role=live: VAD > STT > LLM |           +------------+
 | jobs worker  | | + pgvector + RLS      |   |   (+tools, kb_search, flow) |
 | (api image)  | +-----------------------+   |   > TTS, NC adapter         |--> vendor APIs
 +------+-------+          ^                  |  role=textsim: text runner  |   (Deepgram, Sarvam,
        | post-call jobs   |                  |   for tests and simulations |    AssemblyAI, OpenAI,
        +------------------+                  +-----------------------------+    Azure,           
            S3-compatible storage: recordings (egress), KB documents             ElevenLabs, Cartesia,
                                                                                 Fish Audio, Sanas NC)
```

Deployables:
- `services/api`: FastAPI app (HTTP). The same image runs the `arq` jobs worker.
- `services/voice-worker`: one image, two roles. `live` joins LiveKit rooms; `textsim` runs
  text-mode simulations and test cases with the same pipeline, flow and tool code, and doubles as
  the offline scripted-caller harness (Principle VII).
- `apps/web`: static SPA served from a CDN.

## 2. Repository layout

```
apps/web/src/
  app/            shell, router, auth guard, query client
  routes/<area>/  dashboard, agents, flows, calls, datasets, simulations, review,
                  calibration, issues, channels, knowledge, billing, settings, public
  components/     design-system primitives (Radix + Tailwind tokens), WebCallPanel (shared by
                  003 testing and 008), floating AnalyticsAssistant and VoiceCopilot (006)
  api/            generated TS client from contracts (openapi-typescript)
services/api/app/
  main.py         app factory, router registration
  core/           config, db (sets app.workspace_id for RLS), auth, ids, errors, logging,
                  jobs (arq setup), secrets, rate_limit, idempotency, livekit, url_guard
  <module>/       router.py, schemas.py, models.py, service.py, jobs.py, adapters/ (if any)
  migrations/     Alembic, forward-only
services/api/tests/{unit,contract,integration}/
services/voice-worker/worker/
  entry.py, settings.py, internal_api.py   job entry, config, client for /v1/internal/*
  pipeline.py     session assembly from an AgentVersion snapshot
  call_behavior.py, audio.py, telephony.py silence/max-duration, background audio and
                  pronunciation, SIP specifics (ring duration, DTMF)
  adapters/{stt,llm,tts,nc}/<vendor>.py, adapters/registry.py, adapters/catalog.json
  flow/           executor, registry, nodes/<type>.py, rules, templating (004)
  tools/          ToolProvider, CallControl, builtin tools, http tool, kb_search (005)
  textsim/        runner, replay_caller, persona_caller, mock_tools (008)
  metrics.py      per-turn latency and usage meters, posted to /v1/internal/calls/{id}/events
services/voice-worker/tests/harness/       scripted-caller harness; bench/ holds latency benchmarks
contracts/        openapi.yaml assembled by scripts/assemble_contracts.py from specs/*/contracts
docker-compose.yml, .github/workflows/ci.yml
```

**Core helper ownership.** `core/` belongs to 001. A helper is created by the first feature in
dependency order that needs it: 001 creates config, db, auth, ids, errors, logging, jobs, secrets,
rate_limit; 003 creates livekit, url_guard, idempotency. Later features extend, never fork, them.

**Vendor adapters.** Principle I applies on both sides: the worker has runtime adapters; the API
has `llms/adapters/` (prompt assistant, judges, analytics), `voices/adapters/` (voice listings),
`knowledge/embeddings/` (ingestion) and `voice_commands/` STT key adapters.

## 3. Module ownership and dependencies

| Spec | API modules (`services/api/app/...`) | Web routes |
|---|---|---|
| 001 platform-foundation | core, auth, workspaces, billing, pricing, usage | shell, /login, /register, /billing, /settings, public pages |
| 002 agent-builder | agents, agent_versions, templates, llms, voices, prompt_ai | /agents, /agents/new, /agents/:id/edit, /agents/templates |
| 003 voice-runtime | sessions, calls (write side, admission, pipeline), call_events, webhooks_out, livekit_hooks | /agents/:id/testing |
| 004 flow-agents | flows | /agents/new/flow, /agents/:id/flow |
| 005 tools-knowledge | tools, knowledge | /knowledge-base, agent tools tab |
| 006 calls-analytics | calls (read side), recordings, dashboard, analytics_chat, voice_commands | /dashboard, /calls (detail as `?call=<id>` drawer) |
| 007 quality-evals | analysis_vars, evaluators, evals, annotations, review, calibration | /review, /calibration, agent quality tab |
| 008 testing-simulation | test_cases, test_runs, simulator, datasets | /simulations, /simulations/runs/:runId, /datasets |
| 009 issues-autofix | issues | /issues, /issues/:id |
| 010 channels | phone_numbers, outbound, whatsapp, dialing_policy | /phone-numbers |
| 023 team-roles | team (plus core permissions, mailer) | /settings/team, /invite/:token, /welcome |

Build order: 001 > 002 > 003 > {004, 005, 006, 010} > 007 > 008 > 009.
Real dependencies beyond the chain: 004 needs 005's tool schemas and worker tool code (webhook,
transfer, end nodes); 005 calls two functions in 004's flows service; 009 needs 007 and 008.

**Ports instead of back-dependencies.** When an earlier feature shows data a later one produces,
it defines a port with an empty default and the later feature registers the implementation:
- 006 `CallQualityPort` (verdicts on call list, detail, dashboard) implemented by 007.
- 002 hook registries for config validation and snapshot resolvers, used by 004 (`flow`),
  005 (`tools`, `knowledge`), 007 and 010.
- 003 worker `ToolProvider` and `CallControl` (005), `FlowRunner` (004), and
  `CallControl.apply_overrides()` for per-segment model, voice and STT overrides (004); API `InboundRouter` and
  `OutboundDialProvider` (010); post-call step registry handlers `analyze` and `evaluate` (007).
- 002 `agents.service.validate_override()` and its shared range table: every slider and every
  flow-node override (004) is validated and clamped against one table.
- 002 web editor panel slot `registerEditorPanel`, filled by 007 (quality checks) and others.
- `/calls/:id/compare` (006) redirects to `/simulations/runs/:runId` (008).

**Shared-file edits.** These cross-owner edits are expected and listed in the editing spec's
tasks: 004 T066 into 003 `pipeline.py`; 005 T025 and T077 into 002 version publishing; 008 and
009 into 006 `CallsPage.tsx` (multi-select, add to dataset) and 003 `calls/jobs.py` (simulation
branch); 010 T082 into 001's shell navigation. 003 accepts a `use_draft` flag on test sessions for 005 and 008.

## 4. API conventions

- Base path `/v1`, JSON, snake_case fields, RFC 9457 problem+json errors.
- Auth: `Authorization: Bearer <JWT>`. The API resolves `workspace_id` and runs
  `SET LOCAL app.workspace_id` per transaction; every tenant table has RLS on `workspace_id`.
- Money: decimal strings in the API, `numeric(18,6)` in the database (001 `MoneyUsd` schema).
- Shared schemas `Problem`, `PageMeta`, `MoneyUsd` live in `specs/001-platform-foundation/contracts/core.yaml`.
- IDs are prefixed ULIDs: `ws_`, `usr_`, `agt_`, `agv_`, `flw_`, `tool_`, `kb_`, `doc_`, `call_`,
  `num_`, `wa_`, `wcr_` (WhatsApp caller route), `dnc_` (do-not-call entry), `whd_` (webhook
  delivery), `var_`, `evl_`, `evr_`, `ann_`, `ds_`, `tc_`, `trn_`, `exp_`, `srun_`, `iss_`, `txn_`, `inv_` (team invitation, 023).
  Child rows scoped to one parent (test results, dataset items, fix revisions, validation attempts,
  catalog versions, templates, flow node ids `n_` and edge ids `e_`) use integers, slugs or local
  ids, not platform prefixes.
- Lists: `?page=1&page_size=20` returns `{items, total, page, page_size, total_pages}`.
- Idempotency: `Idempotency-Key` header on POSTs that spend credit or place calls, and on agent
  create and duplicate (double-submit protection).
- Optimistic concurrency where documents are edited whole (flow graphs): `If-Match` revision, 412 on conflict.
- Internal worker endpoints live under `/v1/internal/*` (calls claim, events heartbeat, kb_search,
  textsim), authenticated by a service token.
- Outbound customer webhooks: `Callwright-Signature: t=<unix>,v1=<hmac-sha256>`, 24 h overlap on
  secret rotation, 5 retries on timeout, 408, 429 and 5xx, SSRF guard via `core/url_guard`.

## 5. Core domain objects (shared names)

- **Agent** (`agt_`): name, type `single_prompt | flow`, language, `draft_version_id`, published
  version. **AgentVersion** (`agv_`): immutable snapshot created by every changing save; publish
  pins one for live calls; restore creates a new version. Calls reference the version they ran.
- **AgentConfig** (JSON, versioned schema; one record, merging the reference product's separate
  LLM and agent records): llm {provider, model, temperature}, prompt, begin_message,
  start_speaker, dynamic_variables [{name, default}], stt {provider, model}, tts {provider,
  model, voice_id, speed, expressiveness, volume}, noise_cancellation {provider, model} or null (`sanas` with `vi | st`,
  `ai_coustics` with `standard`),
  call_behavior {end_on_silence_s, max_duration_s, ring_duration_ms, interruption_sensitivity,
  responsiveness}, advanced {webhook_url, webhook_timeout_ms, voicemail_detection, dtmf,
  background_audio, analysis_model, pronunciation[], recording `inherit | on | off`},
  tool_ids[], kb_ids[]. Snapshot-only blocks added by resolvers at version time: `tools` (full
  definitions, secrets as masked refs), `knowledge`, `flow` (graph, position-free hash, compiled
  form). Evaluator settings and analysis variables are per-agent tables (007), not in the config,
  so toggling a check does not create a version.
- **Call** (`call_`): agent_id, agent_version_id, `origin` `live | test | simulation`,
  simulation_run_id, channel `web | sip_inbound | sip_outbound | whatsapp`, from/to, status,
  timestamps, disconnect_reason, `diagnostic`, `recording_enabled` (resolved at admission from
  agent `advanced.recording` and workspace `recording_default`), recording key, transcript items (messages
  and function calls), summary, sentiment, latency stats. Cost lives in 001's `call_costs` table
  keyed by `call_id`. Simulated calls stay out of call history and dashboard totals by default.
- **CallEvent**: per-turn timing (stt_final_ms, llm_ttft_ms, tts_ttfb_ms, e2e_ms), tool calls,
  `flow_transition` events (read via `GET /v1/calls/{call_id}/flow-transitions`, served by
  004's flows module under 006's path), cumulative usage meters. Events double as the worker
  heartbeat; the response can order the call ended for `insufficient_credit`. A reaper ends calls
  silent for 60 s.

Call lifecycle: `queued > ringing > in_progress > ended > processing > completed`. Terminal
outcomes without a conversation: `failed`, `no_answer`, `busy` (details in `diagnostic`, for
example dial failure or caller never joined). A voicemail call goes `ended > processing >
voicemail` and is billed. Disconnect reasons: `user_hangup`, `agent_hangup`, `call_transfer`,
`voicemail_reached`, `inactivity`, `max_duration_reached`, `error`, `concurrency_limit`,
`insufficient_credit`.

Admission (one path for every channel, `calls.service.admit()`): email verified, version
publishable, vendors supported, components priced, balance above zero (001 supplies balance and
the $0.50 mid-call grace), concurrency under a per-workspace advisory lock. Web and outbound calls
are admitted before the room exists; inbound SIP and WhatsApp at `POST /v1/internal/calls/claim`.
Outbound calls also pass 010's dialing policy: workspace do-not-call list and calling-hour window
in the recipient's local time (`dnc_listed`, `outside_calling_hours`, never billed).

## 6. Post-call pipeline

A step table keyed by `(call_id, step)` drives the jobs, each idempotent:
1. `transcript` finalize (blocking)
2. `pricing`: price per component, round each cost line up to $0.001, charge the ledger with key
   `call_charge:{call_id}` (blocking; 001)
3. `analyze`: summary, sentiment, analysis variables (non-blocking; 007)
4. `evaluate`: enabled evaluators (non-blocking; 007). Waits for, or re-queues until, the
   recording is finalized when an enabled check reads audio (`audio_silence`); calls without a
   recording skip audio checks
5. `webhook`: customer `call_analyzed` (003)
6. `complete`: mark `completed` (blocking)

Calls with `origin = simulation` skip `pricing` and `webhook`; the simulation run is billed as a
feature charge instead. Test calls (`origin = test`) are priced and charged like live calls.

## 7. Cross-cutting

- Secrets (vendor keys, SIP and WhatsApp credentials, HTTP tool headers) in `core/secrets.py`,
  encrypted with a KMS-wrapped key; APIs return them masked.
- Recordings: dual-channel audio-only egress started by the API (the worker never holds storage
  credentials), served via 10-minute signed URLs. Skipped when `recording_enabled` is false.
- Observability: OpenTelemetry traces across API and worker carry `call_id`.
- pgvector serves two indexes: knowledge chunks (005) and `call_embeddings` for anomaly detection
  (007). The API image carries PyAV and numpy so jobs can read recordings.
- Feature charges (`flow_assistant`, `voice_copilot`, `analytics_chat`, `prompt_generation`,
  `post_call_analysis`, `eval.<name>`, `simulator.<step>`, `issues.<step>`) and the `embedding`
  component go through `billing.charge_feature()` so usage reporting (001) sees them. Zero-amount charges are
  valid and recorded (for example internal call embeddings), so usage stays complete.
- The analytics assistant never runs model-written SQL: it emits a typed MetricQuery executed over
  RLS-respecting `analytics.*` views by a read-only role (006).
- Server errors return a generic problem body with a `trace_id`; details stay in logs.
- Optional-feature tokens (voice copilot STT keys) are minted on first use, never on page load.
- Launch vendor set: STT Deepgram, Sarvam, AssemblyAI; LLM Azure OpenAI, OpenAI; TTS ElevenLabs,
  Cartesia, Fish Audio; NC Sanas, ai-coustics. Anthropic and Sarvam TTS adapters are deferred.
- House style for all docs: no em dashes.

## 8. Changes from 1.0

Resolved after the ten specs reported conflicts:
- Added: voice-worker `textsim` role; `main.py`; full core helper list and ownership rule;
  API-side adapters; worker file list; repo-root files; shared web components.
- Added Call fields `origin`, `simulation_run_id`, `diagnostic`, `recording_enabled`; cost moved
  to `call_costs`; voicemail lifecycle corrected; admission and dialing policy described.
- AgentConfig extended (tts expressiveness and volume, structured noise cancellation, variable
  defaults, recording override, snapshot-only `tools`, `knowledge`, `flow`); evaluator settings
  moved out of the config; `draft_version_id` on Agent.
- New prefixes `wcr_`, `dnc_`, `whd_`; local-id rule for child rows.
- Ports and expected shared-file edits listed; build order corrected (004 with 005).
- Post-call steps named, simulation skip rule, per-line cost rounding.
- Routes: `/simulations/runs/:runId`, call detail drawer, `/settings`.
- Ownership tasks added: 001 T088 to T090 (secrets, `recording_default`, catalog additions),
  002 T088 and T089 (recording override, `knowledge` snapshot block).

## 9. Changes from 1.1 (live walkthrough merge)

- Post-call `evaluate` waits for the finalized recording when audio checks are enabled.
- Second pgvector use (`call_embeddings`); API image adds PyAV and numpy; zero-amount feature
  charges recorded as usage without a ledger row.
- Ports added: `CallControl.apply_overrides()`, `validate_override()` with the shared range
  table, `registerEditorPanel`. Shared edit added: 010 T082 into 001 navigation.
- Idempotency extended to agent create and duplicate; noise-cancellation ids fixed; launch
  vendor set narrowed; `trace_id` and lazy feature-token rules.

