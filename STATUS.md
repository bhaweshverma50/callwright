# Status and resume point

Last updated: 2026-11-02. Read this first when resuming; `docs/OPERATIONS.md` is the full reference (hosting, deploys, telephony lab, playground, test checkout, design rules).

## Where things stand
- `main` is pushed and deployed (2026-10-26, wave 3 live): Cloud Run API `7ef3756` (migrations through s006_0002), VM jobs worker `7ef3756`, VM voice worker `cf4bea6`, VM LiveKit `v1.13.3`, web from `7ef3756`. Verified on the hosted app with scripted calls: silence check-ins end the call as inactivity, a flow agent call, and the assistant answering "what did my last call cost?".
- Live app: https://callwright-one.vercel.app (sign up with any email; auto-verified; $5 trial credit). Voice calls work from Test agent on the hosted site only (localhost has no LiveKit).
- Specs 001 done, 002 done except the accessibility audit (T085), 003 live (105 of 118).
- Wave 3 complete 2026-10-26: specs 004 (114/114), 005 (99/100), 006 (95/95), 010 (83/85). 701 of 964 tasks. Follow-up fixes merged: flow builder performance and layout, Ask assistant call lookups and push-to-talk, compact dock, silence check-ins (worker), version compare, tabs, call panel layout. Migrations chain s006_0001, s010_0001, s004_0001, s006_0002. Suites: API 1430, worker 468, web 201. Telephony stays fake until `LIVEKIT_SIP_HOST` is set (deploy/vm/README.md). Deleting an agent attached to a number is refused (409 agent_in_use).
- Wave 3a merged and deployed on 2026-10-26: spec 005 tools and knowledge (99 of 100 tasks; T092 quickstart run open) and spec 006 calls and analytics (95 of 95). Migrations chain s003_0002, s005_0001, s006_0001. Suites on the merge: API 1091, worker 385, web 145.

## Voice speed (done 2026-10-26, merged)
Real-vendor live benchmark (`tests/harness/bench`, caller-measured, Deepgram Nova-3, gpt-5.1, ElevenLabs Flash, run from India):

| Change | Answer p50 | Answer p95 | Caller cut-offs |
|---|---|---|---|
| Baseline | 1960 ms | 3062 ms | 3 |
| Priority tier, session and greeting ready before the caller joins | 1778 ms | 2580 ms | 1 |
| Plus short first sentence instruction | 1658 ms | 2207 ms | 0 |
| Deepgram Flux with eager end of turn | 1636 ms | 2169 ms | 0 |

- GPT-5.1 already runs with `reasoning_effort: none` (LiveKit plugin default), so no reasoning setting was needed.
- `OPENAI_SERVICE_TIER=priority` (VM default in render-env.sh) cuts time to first token from about 970 to 700 ms at twice the token price.
- Flux is not worth switching the default to: the gain at the caller is within noise.
- The remaining floor is the network round trip to OpenAI from India (about 550 ms). The next big step is an Azure OpenAI deployment in an Indian region (the `azure_openai` provider is already the default and used when Azure secrets exist).
- Spoken filler before tools and "still checking" belong to spec 005 (tools), briefed to the `w3-tools` build.

## Hosted call fix (2026-10-26)
- Calls ended after one reply with the timer stuck at 0:00. Cause: LiveKit server 1.8.4 on the VM is too old for livekit-client 2.22; once the agent joined before the caller, the browser's publish negotiation timed out, the client did a full reconnect (leave and rejoin), and the worker treated the leave as a hang-up. Fixed by LiveKit 1.13.3 (verified with a scripted hosted call) and by marking the call live once the room is joined.
- `apps/web/scripts/e2e-call.mjs` places a real browser test call with a fake microphone (`API=... WEB=... node scripts/e2e-call.mjs caller.wav out-dir [template]`); defaults target the local stack.
- Follow-up: the worker hangs up as soon as the caller's participant leaves; a short rejoin grace would survive network blips but must not bill the grace seconds.

## Telephony lab (2026-10-27, deployed 7a9a4fe)
- Real SIP without a carrier: Asterisk `lab-pbx` service on the VM (deploy/vm/lab-pbx, compose profile `lab`) stands in for the phone company. Softphones `phone1`/`phone2` register on 5080 and call Callwright numbers through livekit-sip; Callwright's outbound calls ring them (last digit picks the phone). No public phone network, no per-minute cost, idle shutdown kept.
- Verified locally with the real images in one network namespace: inbound opens a `call-in-` room with the SIP participant; outbound rings a registered phone with the number as caller id and returns 486 busy / 480 unavailable. Not yet verified: RTP across the VM's public IP and a voice agent answering (needs the deploy).
- Fixed on the way: the compose `sip` service mounted its config where livekit/sip v1.2.0 never reads it (the entrypoint forces `--config=/sip/config.yaml`), so it would not have started. SIP over TLS is now only configured once certificates exist.
- `render-env.sh` and `deploy.sh` now keep `LIVEKIT_SIP_HOST` (and the lab flag) across renders and deploys instead of silently dropping them.
- To turn on: deploy/vm/README.md, "Lab mode" (DNS `sip`, firewall rule `callwright-lab-pbx`, render with `CW_LIVEKIT_SIP_HOST=sip.bhawesh.dev CW_LAB_PBX=true`, API deploy with `LIVEKIT_SIP_HOST`, import `+919000000100` with termination `127.0.0.1:5080`). Then T067 (SIPp scenarios) and T069 (channels quickstart run) can be done against it.

## Call fixes from the first lab SIP call (2026-10-27, deployed 16fa881)
- Agent never hung up: single-prompt agents had no end_call tool unless one was attached. Now every single-prompt agent gets a built-in `end_call` (unless it has its own), a prompt line to call it in the goodbye reply without waiting for the caller, and a worker safety net that hangs up 2 s after a reply ending in a goodbye (cancelled if the caller speaks). end_call waits for the goodbye to finish playing before hanging up (it used to cut it off). The preset's spoken goodbye line is now empty by default (it doubled the goodbye).
- Agent transcript lines start at the turn's first audio (they were stamped when playout ended). Turns whose caller speech voice detection missed now get a latency from the final transcript time instead of "n/a".
- Vendor plugins are imported in prewarm (a 2.6 s event-loop stall at call start). "85% heard" reads "85% sure" (it is STT confidence).
- Dashboard: sparkline dot was stretched into an oval and the line stopped short (pathLength with a non-scaling stroke); copilot dock mic is now a soft secondary button with a divider before "Ask about your data".
- Sentiment shows "Unknown" because post-call analysis is spec 007 (not built; pipeline step `analyze` is skipped).

## Homepage playground, test checkout, UI polish (2026-10-27, committed 51ccbe6, deployed with 1881139)
- Homepage playground: visitors call a demo agent from the browser (clinic, roadside, loan) and see each reply's latency and the running cost. Public `GET /v1/public/demo` and `POST /v1/public/demo-calls`, 3 calls per IP per hour, 2 minutes per call, charged to the demo workspace (created: `ws_01M5YB54ZTTDHJSVXQCB9D21FF`, ids in `deploy/cloudrun/deploy.sh`). Details: docs/OPERATIONS.md section 5.
- Test checkout: "Add funds" opens `/checkout/{session}` in the web app with Stripe-style test cards for success and every decline. Section 6.
- `useWebCall` hook extracted from `WebCallPanel` (shared with the playground); flow builder nodes and canvas restyled solid and crisp; dashboard sparkline dot and draw-in fixed; copilot dock mic is secondary; VM rollouts prune old images.
- Suites at this point: API 1433+ (demo and checkout tests added), web 206, contracts up to date.
- Deploy: commit, then `deploy.sh ... build api` and the Vercel deploy (no VM or voice change).

## Wave 4 (started 2026-10-27)
- 4a, spec 007 quality and evals: merged into main 2026-10-27 (merge 2aecc70, 90/90 tasks). Post-call summary, sentiment and analysis variables for every call, quality checks with verdicts and reasons, labels, calibration, custom checks, review queue; Quality tabs in the call drawer and agent editor, Review and Calibration pages. Migration `s007_0001` (after `s006_0002`). New optional settings `EVAL_JUDGE_MODELS` (default `openai/gpt-5-mini`), `EVAL_JUDGE_MODEL`, `EVAL_CONCURRENCY=4`, `EVAL_TIMEOUT_S=60`, `EVAL_JUDGE_PASS_CUTOFF=0.5`, `CALIBRATION_MIN_SAMPLE=5`; no new secrets. The migrate role also syncs the built-in evaluator catalog.
- Suites on the merge: API 1688, web 251, worker 480, contracts and generated types up to date.
- Deployed with 1881139 (API, VM jobs worker, web), verified 2026-11-02.
- Open: the `evals` key in agent config (002) is superseded by per-agent evaluator settings and can be removed; judges run without a pinned temperature (the LLM client has no parameter); judge quality is untested against real models.
- 4b, spec 008 testing and simulation: merged and deployed 2026-11-02 (API and jobs worker `23bb55e`, voice and textsim `181f0ed`, web; verified on the hosted stack with a judged test case and a 16-turn persona simulation) (94/95 tasks; T085 live latency benchmark deferred, offline benchmark unchanged at p50 666 ms). Test cases with LLM-judged runs (Testing tab on `/agents/:id/testing?tab=cases`), text simulations that replay a past call or let a persona caller play against any agent version, batch scorecards and comparison, datasets (`/simulations`, `/simulations/runs/:runId`, `/datasets`). Simulated calls are stored as calls with `origin = simulation`, so 007 scores them unchanged; they skip the concurrency limit, the mid-call credit guard and customer webhooks. Migration `s008_0001` (after `s007_0001`).
- New optional settings: `SIMULATOR_MODEL` (default `openai/gpt-5-mini`), `TESTCASE_GENERATOR_MODEL`, `SIM_MAX_CONCURRENCY=10`, `SIM_TIMEOUT_S=60`; voice worker textsim `TEXTSIM_MAX_JOBS=10`, `TEXTSIM_JOB_TIMEOUT_S=900` (and `REDIS_URL`, rendered into `voice.env`). No new secrets.
- Deploy 008: `deploy.sh ... build migrate api`; `deploy.sh ... build-voice`; copy `deploy/vm/docker-compose.yml` and `render-env.sh` to the VM, render with the new API and voice tags, `docker compose pull worker voice textsim && docker compose up -d` (new `textsim` service: voice image with `WORKER_ROLE=textsim`, queue `arq:textsim`, health on 127.0.0.1:8193; jobs worker gains `dispatch_simulation`, `dispatch_test_case`, `judge_result` and crons `sweep_simulations`, `purge_simulation_data`); then Vercel.
- Open: offline (no keys) verdicts only prove plumbing; judges run without a pinned temperature (same as 007); tool description edits do not reach compiled flow nodes in variants; batches over 100 usable calls are refused (422).
- Also fixed on merge: the API now percent-decodes the Redis password in `REDIS_URL` (render-env.sh encodes it).

## Wave 5, spec 009 issues and auto-fix (merged 2026-11-02, not deployed)
- 61/61 tasks. Recurring check failures are clustered per agent into issues, each gets an AI or manual fix (eight fix kinds), validated with a control and a treatment batch of 008 simulations over the same affected and guard calls, then applied as a new agent version (Issues and issue pages). Migration `s009_0001` (after `s007_0002`); new optional `ISSUES_MODEL` (defaults to `SIMULATOR_MODEL`); scikit-learn added to the API image. Jobs worker: jobs `detect_issues`, `finalize_validation`, `sweep_issues`, `audit_applied_issues`; crons `sweep_issues` (every minute at :40) and `audit_applied_issues` (05:30 daily). No voice worker change.
- Deploy: `deploy.sh ... build migrate api`, VM jobs worker on the new API tag, Vercel.
- Open: with offline models validation correctly reports no improvement, so apply was proven by integration tests rather than live; under load 008's internal result transaction can deadlock against 007's analyze step (the runner retries, but some simulated calls skip analysis), worth a lock-order fix; factual consistency is not applicable without knowledge search, so issues headlined by it cannot be validated by simulation.

## Fixes on 2026-11-02 (pushed, deploy with 009)
- API used offline text for Azure-configured agents on the hosted app (no Azure key); it now falls back to OpenAI like the voice worker, and staging/prod never answer with offline text (deployed `a54c168`).
- Calls under 15 s or with under 40 caller characters skip the AI summary and paid judges (`too_short`; `ANALYSIS_MIN_DURATION_S`, `ANALYSIS_MIN_CALLER_CHARS`; migration `s007_0002`). Free checks always run.
- CI green again: forward-only migrations are checked as one linear chain instead of downgrade and upgrade.
- Simulation lists and comparison stay current; rounded scores; audio-only checks listed once.
- One composer and a thinking line (waveform, changing verb, elapsed time) for every AI surface; calmer agent editor tabs; movable assistant dock; the save bar shows Discard and Save only with unsaved changes.

## Public pages (2026-11-02, deployed)
- Home, pricing and enterprise redesigned without template patterns (two-column bands with ruled rows, solid headlines, one primary action). Home adds a vendor strip with real wordmarks (`public/logos/vendors`), an interactive chain demo, a 31 s product tour (`public/media/tour.*`, re-record with `apps/web/scripts/record-tour.mjs`), a quality scroll story and the template rail. The playground shows only scenario, part and call button until a call starts.

## Next, in order
1. Place a hosted test call to confirm the faster greeting and answers (last measured live: greeting 2.1 s, answer 2.7 s). Note: `worker-hint` prints the HEAD tag; pin `CW_API_IMAGE` and `CW_VOICE_IMAGE` to tags that were actually built.
2. Wave 3a is live. Notes: new secrets need `deploy.sh ... setup` before `api` (it grants the API service account access); the dashboard counts live calls only. New optional env: `ANALYTICS_CHAT_MODEL`, `VOICE_COMMAND_MODEL`, `RECORDING_URL_TTL_S`, `SIP_OUTBOUND_TRUNK_ID`; `DEEPGRAM_API_KEY` now mounted on the API. Uploads stay in memory (`STORAGE_MODE=fake`) until a bucket exists.
3. Wave 3b: specs 004 (flows, uses 005's tool ports) and 010 (channels). Then wave 4 (007, 008) and wave 5 (009).
4. Later: recording service (LiveKit egress; `RECORDINGS_ENABLED=false` today), an object storage bucket (uploads are in memory on Cloud Run), Azure OpenAI in India, key rotation.

## Deploy
See `deploy/cloudrun/README.md` and `deploy/vm/README.md`. Every gcloud command passes the personal account and project explicitly; the machine's default gcloud account belongs to another organisation.
- Changes to the seed templates (`services/api/app/templates/seed`) or the built-in check catalog (`app/evaluators/builtins`) need `deploy.sh ... migrate` too: the migrate job syncs both into the database; `build api` alone does not.
- 2026-11-02: templates gained an Identity rule (never name the AI vendor) and intent fulfilment is on by default; deployed as API `7ba6b77` plus migrate, verified on the hosted API.
