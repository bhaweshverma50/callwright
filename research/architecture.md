# Callwright Architecture Conventions (HLD)

Shared by every spec and plan under `specs/`. Plans MUST use these names, paths and patterns.
Deviations go in the plan's Complexity Tracking table.

## 1. Runtime topology

```
                 +---------------------------- Browser (apps/web) ----------------------------+
                 | React SPA, TanStack Query, livekit-client (web test calls, voice Q&A)       |
                 +-------+-----------------------------+--------------------------------------+
                         | HTTPS /v1 (JWT)             | WebRTC (room token)
                         v                             v
 +----------------------------------+        +---------------------------+   SIP trunk   +------------+
 | services/api  (FastAPI)          |------> | LiveKit (Cloud/self-host) |<------------> | Carrier /  |
 |  REST + webhooks (Stripe, LK,    | create |  rooms, SIP, egress       |               | Twilio etc |
 |  Meta), RLS-scoped DB sessions,  | rooms, +----------+----------------+               +------------+
 |  dispatch rules, signed URLs     | tokens            | agent dispatch                 +------------+
 +-------+--------------+-----------+                   v                                | WhatsApp   |
         | enqueue      | SQL                 +-----------------------------+  Meta     | Business   |
         v              v                     | services/voice-worker       |<--------->| Calling    |
 +--------------+ +-----------------------+   | LiveKit Agents (Python)     |           +------------+
 | Redis (arq)  | | Postgres 16           |<--| VAD > STT > LLM(+tools,RAG) |
 | jobs worker  | | + pgvector + RLS      |   |  > TTS, NC adapter, flows   |--> vendor APIs
 | (api image)  | +-----------------------+   | per-turn metrics to API     |   (Deepgram, Sarvam,
 +------+-------+          ^                  +-----------------------------+    AssemblyAI, OpenAI,
        | post-call jobs   |                                                      Azure, Anthropic,
        +------------------+   S3-compatible storage: recordings, KB documents    ElevenLabs, Cartesia,
                                                                                  Fish Audio, Sanas NC)
```

Two deployables plus one job process:
- `services/api`: FastAPI app (HTTP); the same codebase also runs as the `arq` jobs worker.
- `services/voice-worker`: LiveKit Agents worker, stateless, horizontally scaled.
- `apps/web`: static SPA served from a CDN.

## 2. Repository layout

```
apps/web/src/
  app/            shell, router, auth guard, query client
  routes/<area>/  dashboard, agents, flows, calls, datasets, simulations, review,
                  calibration, issues, channels, knowledge, billing, settings, public
  components/     design-system primitives (Radix + Tailwind tokens)
  api/            generated TS client from contracts (openapi-typescript)
services/api/app/
  core/           config, db (session sets app.workspace_id for RLS), auth (JWT verify), ids, errors
  <module>/       router.py, schemas.py, models.py, service.py, jobs.py (if any)
  migrations/     Alembic, forward-only
services/api/tests/{unit,contract,integration}/
services/voice-worker/worker/
  entry.py        job entry, loads AgentConfig snapshot by agent_version_id
  pipeline.py     session assembly from config
  adapters/{stt,llm,tts,nc}/<vendor>.py   one file per vendor (Principle I)
  flow/           flow-graph executor (node state machine)
  tools/          builtin tools (end_call, transfer, dtmf, kb_search, http)
  metrics.py      per-turn latency and usage meters, posted to /v1/internal/calls/{id}/events
services/voice-worker/tests/harness/   scripted-caller offline harness (Principle VII)
contracts/        openapi.yaml assembled from specs/*/contracts/*.yaml
```

## 3. Module ownership (spec to API modules)

| Spec | API modules (`services/api/app/...`) | Web routes |
|---|---|---|
| 001 platform-foundation | core, auth, workspaces, billing, pricing, usage | shell, /login, /register, /billing, public pages |
| 002 agent-builder | agents, agent_versions, templates, llms, voices, prompt_ai | /agents, /agents/new, /agents/:id/edit, /agents/templates |
| 003 voice-runtime | sessions (web calls), calls (write side), call_events, webhooks_out, livekit_hooks | /agents/:id/testing |
| 004 flow-agents | flows | /agents/new/flow, /agents/:id/flow |
| 005 tools-knowledge | tools, knowledge | /knowledge-base, agent tools tab |
| 006 calls-analytics | calls (read side), recordings, dashboard, analytics_chat, voice_commands | /dashboard, /calls, /calls/:id/compare |
| 007 quality-evals | analysis_vars, evaluators, evals, annotations, review, calibration | /review, /calibration, agent quality tab |
| 008 testing-simulation | test_cases, test_runs, simulator, datasets | /simulations, /datasets, agent testing tab |
| 009 issues-autofix | issues | /issues, /issues/:id |
| 010 channels | phone_numbers, outbound, whatsapp | /phone-numbers |

Dependencies: every spec depends on 001; 003 on 002; 004 and 005 on 002 and 003; 006 on 003;
007 on 006; 008 on 007; 009 on 007 and 008; 010 on 003.

## 4. API conventions

- Base path `/v1`, JSON, snake_case fields, RFC 9457 problem+json errors.
- Auth: `Authorization: Bearer <JWT>`. The API resolves `workspace_id` and runs
  `SET LOCAL app.workspace_id` per transaction; every tenant table has RLS on `workspace_id`.
- IDs are prefixed ULIDs: `ws_`, `usr_`, `agt_`, `agv_` (agent version), `flw_`, `tool_`, `kb_`,
  `doc_`, `call_`, `num_`, `wa_`, `var_`, `evl_` (evaluator), `evr_` (evaluator run), `ann_`,
  `ds_`, `tc_`, `trn_` (test run), `exp_`, `srun_` (simulation run), `iss_`, `txn_`.
- Lists: `?page=1&page_size=20` returns `{items, total, page, page_size, total_pages}`.
- Idempotency: `Idempotency-Key` header on POSTs that spend credit or place calls.
- Internal worker endpoints live under `/v1/internal/*`, authenticated by a service token.
- Outbound customer webhooks are signed with HMAC-SHA256 in a `Callwright-Signature` header.

## 5. Core domain objects (shared names)

- **Agent** (`agt_`): name, type `single_prompt | flow`, language, current draft config,
  pinned published version. **AgentVersion** (`agv_`): immutable config snapshot. Calls
  reference the version they ran.
- **AgentConfig** (JSON, versioned schema): llm {provider, model, temperature}, prompt,
  begin_message, start_speaker, dynamic_variables[], stt {provider, model}, tts {provider,
  model, voice_id, speed?}, noise_cancellation, call_behavior {end_on_silence_s,
  max_duration_s, ring_duration_ms, interruption_sensitivity, responsiveness}, advanced
  {webhook_url, webhook_timeout_ms, voicemail_detection, dtmf, background_audio,
  analysis_model, pronunciation[]}, tool_ids[], kb_ids[], flow_id?, evals config.
- **Call** (`call_`): agent_id, agent_version_id, channel `web | sip_inbound | sip_outbound |
  whatsapp`, from/to, status (lifecycle below), timestamps, disconnect_reason, recording key,
  transcript turns, summary, sentiment, analysis variables, cost breakdown, latency stats.
- **CallEvent**: per-turn timing (stt_final_ms, llm_ttft_ms, tts_ttfb_ms, e2e_ms), tool calls,
  flow transitions, usage meters (tokens in/out, TTS characters).

Call lifecycle: `queued > ringing > in_progress > ended > processing > completed`, plus terminal
`failed`, `no_answer`, `busy`, `voicemail`. Disconnect reasons: `user_hangup`, `agent_hangup`,
`call_transfer`, `voicemail_reached`, `inactivity`, `max_duration_reached`, `error`,
`concurrency_limit`, `insufficient_credit`.

## 6. Post-call pipeline (jobs, in order)

`call.ended` then: finalize transcript; price the call and charge the ledger (001); summary,
sentiment and analysis variables (007); run enabled evaluators (007); send the customer webhook
`call_analyzed` (003); mark `completed`. Each step is idempotent, keyed by call_id plus step.

## 7. Cross-cutting

- Secrets (vendor keys, SIP credentials) live in a `secrets` table encrypted with a KMS key; the
  API returns them masked.
- Recordings: LiveKit egress to S3, served via 10-minute signed URLs.
- Observability: OpenTelemetry traces across API and worker carry `call_id` as an attribute.
- Feature charges (evals, simulations, analytics chat, prompt generation) go through
  `billing.charge_feature()` so usage reporting (001) sees them.
- House style for all docs: no em dashes.
