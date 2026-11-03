# Callwright operations handbook

How the hosted demo is put together, how to deploy and test each piece, and why things are the
way they are. `STATUS.md` is the short "where are we" page; this file is the reference behind it.
Last updated 2026-10-27.

## 1. Hosted topology

| Piece | Where | Notes |
|---|---|---|
| Web app | Vercel, https://callwright-one.vercel.app (personal scope `bhaweshverma50s-projects`) | `apps/web`, Vite + React |
| API | Cloud Run `callwright-api`, asia-south1, scales to zero | `services/api`, one image for `api`, `worker`, `migrate` |
| Migrations | Cloud Run job `callwright-migrate` | same image, `ROLE=migrate` |
| Realtime VM | `callwright-rtc` (e2-medium, asia-south1-a, static IP 34.180.13.164, internal 10.160.0.2) | Caddy, LiveKit 1.13.3, Redis, jobs worker, voice worker, livekit-sip, lab PBX (`deploy/vm`) |
| Database | Supabase project `callwright` (ap-south-1) | pgvector, RLS, roles `callwright_app` / `callwright_admin` |
| Secrets | GCP Secret Manager, project `callwright-dev` | rendered onto the VM by `deploy/vm/render-env.sh` |
| DNS | Cloudflare, zone bhawesh.dev | `rtc` and `sip` A records to 34.180.13.164, DNS only (never proxied) |

The VM powers itself off after 15 idle minutes (`deploy/vm/idle-shutdown.sh`). The API wakes it
when Redis is unreachable and answers 503 `waking_up` meanwhile; the web app's wake gate retries
and shows "Starting the call servers". Calls in progress keep the VM up.

### Accounts (personal only)

- GCP: always `--account bhaweshverma50@gmail.com --project callwright-dev`. The machine's
  default gcloud account belongs to another organisation and must never be used here.
- Vercel: CLI user `bhaweshverma50`, scope `bhaweshverma50s-projects`. The Vercel MCP connector
  in Claude sessions is a company account: never deploy through it.
- GitHub: private repo `bhaweshverma50/callwright`, commits as `bhaweshverma50@gmail.com`.

## 2. Deploying

Image tags are the short git sha at build time, so commit before building.

```bash
cd ~/Downloads/MyStuff/Projects/callwright
ACCOUNT=bhaweshverma50@gmail.com; PROJECT=callwright-dev; ZONE=asia-south1-a
TAG=$(git rev-parse --short HEAD)

# API (add `setup` first when a new secret was added; add `migrate` when migrations changed)
deploy/cloudrun/deploy.sh $PROJECT $ACCOUNT build api
# Voice worker image (only when services/voice-worker changed)
deploy/cloudrun/deploy.sh $PROJECT $ACCOUNT build-voice

# VM: copy compose files when deploy/vm changed, then roll the workers and prune old images
gcloud compute instances start callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT
gcloud compute scp --recurse deploy/vm/docker-compose.yml deploy/vm/render-env.sh \
  deploy/vm/livekit.yaml.tmpl deploy/vm/sip.yaml.tmpl deploy/vm/sip-tls.yaml.tmpl deploy/vm/lab-pbx \
  callwright-rtc:/opt/callwright/ --zone $ZONE --account $ACCOUNT --project $PROJECT
gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
  "cd /opt/callwright && CW_API_IMAGE=asia-south1-docker.pkg.dev/$PROJECT/callwright/api:$TAG \
   CW_VOICE_IMAGE=asia-south1-docker.pkg.dev/$PROJECT/callwright/voice-worker:$TAG ./render-env.sh \
   && sudo docker compose pull worker voice && sudo docker compose up -d && sudo docker image prune -af"

# Web
cd apps/web && vercel deploy --prod --scope bhaweshverma50s-projects
```

What `deploy.sh api` sends to Cloud Run (it replaces the whole env each time, so anything not in
the script is dropped):

| Variable | Value | Why |
|---|---|---|
| `LIVEKIT_SIP_HOST` | kept from the running service unless passed (`LIVEKIT_SIP_HOST=` turns SIP off) | telephony on |
| `DEMO_WORKSPACE_ID`, `DEMO_AGENTS`, `DEMO_CALLS_PER_HOUR` | defaults in `deploy.sh` (section 5) | homepage playground |
| `STRIPE_MODE=fake`, `ENABLE_FAKE_CHECKOUT=true` | fixed | test checkout (section 6) |
| `AUTH_AUTO_VERIFY_EMAIL=true` | fixed | demo sign-ups need no email |
| `WAKE_VM_*` | fixed | API starts the VM |

`render-env.sh` on the VM is sticky in the same way: it remembers the images, `LIVEKIT_SIP_HOST`
and `LAB_PBX` in `.env`, and writes `COMPOSE_PROFILES` so a plain `docker compose up -d` keeps
the SIP service and the lab PBX running.

**Disk:** the VM disk is 19 GB and each voice worker image is about 2 GB. It filled up on
2026-10-27 after six rollouts ("no space left on device" during pull). Every rollout now ends with
`sudo docker image prune -af`, which keeps the images of running containers; old tags can be
pulled again from Artifact Registry.

Auto mode in Claude sessions blocks API builds and production deploys even with approval, so
the owner runs the commands above; Claude prepares them.

## 3. Telephony without a carrier (lab PBX)

Goal: real SIP calls for demos with no phone company, no per-minute cost and no always-on VM.
VICIdial was considered and rejected: it is a whole call centre suite (dialer, agent screens,
campaigns) on an old Asterisk and its own OS, it overlaps Callwright itself, cannot hand calls to
LiveKit agents, and is too heavy to start and stop on demand.

```
softphone --SIP 5080--> Asterisk (lab-pbx) --127.0.0.1:5060--> livekit-sip --> LiveKit room + voice agent
```

- `deploy/vm/lab-pbx`: Asterisk 20 from Ubuntu's archive, built on the VM
  (`docker compose build lab-pbx`), compose profile `lab`. It stands in for the carrier.
- Softphones (Linphone, Zoiper, MicroSIP): users `phone1` and `phone2`, domain
  `sip.bhawesh.dev:5080`, UDP, codec G.711. Password: `sudo cat /opt/callwright/lab-pbx/phone-password`
  on the VM (made on the first render, never leaves the VM).
- Inbound: a softphone dials a Callwright number, for example `+919000000100`.
- Outbound: Callwright dials a number and the last digit picks the softphone (`+919000000001`
  rings `phone1`). Not registered answers 480, busy 486.
- Callwright number setup: Phone numbers, Import: the E.164 number, termination `127.0.0.1:5080`,
  transport UDP, no credentials.
- Firewall rule `callwright-lab-pbx` (tag `callwright-rtc`): udp/tcp 5080, udp 52000-52199
  (Asterisk media), udp 51000-51999 (livekit-sip media). Port 5060 stays closed until a carrier.
- Security: only `phone1`/`phone2` (32 hex password) and livekit-sip on 127.0.0.1 are accepted;
  the dialplan reaches nothing but livekit-sip and the two softphones, so a guessed password cannot
  place paid calls. Rotate by deleting `lab-pbx/phone-password` and rendering again.
- A softphone cannot wake a sleeping VM: open the web app first, then call.
- Bug fixed on the way: `livekit/sip` v1.2.0 forces `--config=/sip/config.yaml`, so the old
  `SIP_CONFIG_FILE` mount was never read. SIP over TLS (5061, needed for WhatsApp) is only
  configured once `sip-certs/fullchain.pem` exists.
- Real numbers later: any SIP trunk (Telnyx, Twilio; Indian numbers need an Indian carrier and
  KYC) pointed at the same setup; `deploy/vm/README.md`, "Real phone numbers".

## 4. Call behaviour fixes (2026-10-27)

From the first lab SIP call, where the agent said goodbye and then kept talking:

- Every single-prompt agent gets a built-in `end_call` tool unless it has its own
  (`services/voice-worker/worker/tools/registry.py`), and an instruction to call it in the
  goodbye reply without waiting for the caller (`ENDING_INSTRUCTION` in `worker/pipeline.py`).
- Safety net: a reply that ends in a goodbye ("goodbye", "bye now", "take care", "have a good
  day") hangs up 2 s after it finishes playing unless the caller starts speaking
  (`ends_with_goodbye`, `GOODBYE_HANGUP_DELAY_S` in `worker/call_behavior.py`).
- `end_call` waits for the reply that called it to finish playing before hanging up; it used to
  cut the goodbye off. The "End the call" preset no longer speaks its own second goodbye.
- Transcript lines for the agent start at the turn's first audio, not when playback ended.
- Turns where voice activity detection missed short phone speech get a latency anchored at the
  final transcript instead of "n/a".
- Vendor plugins load in the worker's prewarm (a 2.6 s stall at call start before).
- "85% heard" in transcripts now reads "85% sure": it is speech recognition confidence.
- Sentiment shows "Unknown" until spec 007 (post-call analysis) ships.

## 5. Homepage playground

Visitors call a real agent from the browser on the home page, without an account.

- API: `GET /v1/public/demo` (scenario keys, never touches Redis so a page view does not wake the
  VM) and `POST /v1/public/demo-calls` `{agent: "clinic"}` (`services/api/app/demo/router.py`,
  contract `specs/003-voice-runtime/contracts/demo.yaml`). It reuses `start_web_call` with a
  workspace but no user.
- Web: `apps/web/src/routes/public/playground` (scenario content in `scenarios.ts`). The call
  logic is the `useWebCall` hook shared with the test-call panel. While the VM wakes, the console
  shows its own progress and the full-page wake overlay stays hidden (`inlineWake` in
  `api/wakeGate.ts`). With no demo agents configured, the old scripted sample call plays.
- Limits: 3 calls per visitor IP per hour (`DEMO_CALLS_PER_HOUR`), 2 minutes per call (agent
  setting plus a client-side cutoff), and all spend comes out of the demo workspace balance, which
  is the hard cap. Out of calls or credit, visitors see "Create account".

Demo workspace (created 2026-10-27 through the hosted API):

| | |
|---|---|
| Account | `playground@bhawesh.dev`; password only in `~/.config/callwright/demo-account.json` on the owner's Mac |
| Workspace | `ws_01M5YB54ZTTDHJSVXQCB9D21FF`, $25 balance at creation |
| `clinic` | Acme Health Clinic front desk, `agt_01M5YB55MNVTVK1MHD4E70V21K` (template healthcare-triage-booking) |
| `roadside` | Acme Auto Assist roadside, `agt_01M5YB56PF56Z0RA344HA05DXP` (template automotive-roadside-ev) |
| `loan` | Acme Bank payment reminder, `agt_01M5YB57R9YATWAP5HXC8XJ82W` (template banking-collections, customer "Jordan Lee") |

All three are published with `max_duration_s: 120`. Top up the workspace by signing in as the
demo account and adding funds (test checkout). To change agents, edit `DEMO_AGENTS` in
`deploy/cloudrun/deploy.sh` and deploy the API; `DEMO_WORKSPACE_ID=` turns the playground off.

## 6. Test checkout (STRIPE_MODE=fake)

"Add funds" goes to `/checkout/{session}` in the web app (`apps/web/src/routes/checkout`), laid
out like a hosted checkout and marked "Test mode". The API behind it is
`/v1/dev/fake-checkout/{id}` (`services/api/app/dev/router.py`, not in the public contract). Like
Stripe's test cards, the card number decides the outcome:

| Card | Outcome |
|---|---|
| 4242 4242 4242 4242 (Visa) | succeeds |
| 5555 5555 5555 4444 (Mastercard) | succeeds |
| 4000 0000 0000 0002 | card declined |
| 4000 0000 0000 9995 | insufficient funds |
| 4000 0000 0000 0069 | expired card |
| 4000 0000 0000 0127 | incorrect CVC |
| 4000 0000 0000 0119 | processing error |

Any future expiry and any 3 digit code. Any other valid number is declined with a hint to use a
test card; invalid numbers, past expiry, short codes and an empty name are refused per field.
A success signs a `checkout.session.completed` event with the webhook secret and runs the same
verification and handler as a real Stripe webhook, so the balance and transactions behave exactly
as in production. The mock web API (`vite --mode mock`) mirrors the same cards.

## 7. Design rules learned the hard way

- No emojis anywhere. No coloured side-stripe borders for active items.
- No gradient washes or glows on small cards or behind them (flow builder nodes were redone on
  2026-10-27): solid surface, crisp 1px border, tight shadow; colour only in the icon chip.
  Gradients belong on primary buttons and hero moments.
- Sparklines: the dot is an HTML element (an SVG circle stretches with
  `preserveAspectRatio="none"`), and the draw-in is a clip, not `pathLength` (with a non-scaling
  stroke the dash is measured in screen pixels and the line stops short).
- Copilot dock: one gradient action ("Ask about your data"); the mic is a soft secondary button.
- Verify UI in real Chrome (Playwright), light and dark, desktop and 390 px. Mock mode with
  seeded calls: `pnpm exec vite --mode mock`, sign in as `ops@halcyon-dental.com` /
  `correct-horse-9`, and `(await import("/src/mocks/calls/handlers.ts")).seedMockCalls(45)` before
  signing in.
- Docs in this repo: no em dashes (a hook rejects them).

## 8. Local development and tests

- `docker compose up -d` at the root: Postgres on 55432, Redis on 56379. API on 8100, web on 5180.
- Parallel work uses git worktrees (`../callwright-<name>`) with their own `TEST_DB_NAME`,
  Redis db and ports; never point tests at the shared `callwright` dev database.
- Suites: API `uv run pytest` (+ ruff, mypy), voice worker `uv run pytest`, web
  `pnpm typecheck && pnpm lint && pnpm exec vitest run && pnpm build`, `make contracts-check`,
  `pnpm gen:api:check`.
- Hosted call diagnostics: hosted DB reads are blocked for Claude; use Cloud Run logs and
  `sudo docker compose logs voice worker sip lab-pbx` on the VM.

## 9. Testing and simulation (spec 008)

- Test cases, test runs, simulations (replay and persona), batches with scorecards and datasets.
  API modules `test_cases`, `test_runs`, `simulator`, `datasets`; migration `s008_0001`.
- Simulated conversations run in the voice worker image as a second process,
  `WORKER_ROLE=textsim` (compose service `textsim` on the VM, health on 127.0.0.1:8193). It
  consumes the arq queue `arq:textsim` (jobs `run_single_turn`, `run_simulation`) on the VM Redis
  and talks only to the internal API (`/v1/internal/test-runs/...`, `/v1/internal/simulation-runs/...`,
  `/v1/internal/calls/{id}/events`, knowledge search). Tools never reach customer systems: HTTP
  tools and webhook nodes answer with their mock response, the recorded output (replay) or a
  generated stand-in, and each answer is labelled.
- The API's jobs worker gates the runner: `dispatch_simulation` and `dispatch_test_case` take a
  slot of the per-workspace semaphore (`sim:sem:{workspace_id}`, `SIM_MAX_CONCURRENCY`, default
  10), `judge_result` judges test case replies, `sweep_simulations` (every minute) fails runs and
  test cases whose runner went silent, `purge_simulation_data` (daily) clears persona briefs and
  simulated transcripts once the base call's transcript is gone.
- A simulated call is a `calls` row with `origin = simulation`: it goes through finalize,
  analysis and 007's evaluators, never through call pricing, call charges, customer webhooks,
  the mid-call credit guard or the concurrent-call limit, and Call History hides it unless the
  origin filter includes it. Runs are billed as feature charges `testing.run`, `testing.generate`,
  `simulation.replay`, `simulation.persona`, `simulation.persona_extraction`,
  `simulation.tool_synth`, once per run.
- Settings (all optional): API `SIMULATOR_MODEL` (default `openai/gpt-5-mini`),
  `TESTCASE_GENERATOR_MODEL`, `SIM_MAX_CONCURRENCY`, `SIM_TIMEOUT_S`; text runner `REDIS_URL`
  (rendered into `voice.env`), `TEXTSIM_MAX_JOBS`, `TEXTSIM_JOB_TIMEOUT_S`. No new secrets.

## 10. Issues and auto-fix (spec 009)

- API module `issues` (`/v1/issues...`), web routes `/issues` and `/issues/:id`; migration `s009_0001` (after `s008_0001`). No worker code: validation batches are 008 experiments with `source = issue_validation`.
- Detection (`detect_issues` job, one per agent at a time): current failed verdicts of enabled checks in the window (7, 14, 30 or 90 days; live calls, plus simulated ones when asked), turn failures collapsed per call, grouped by check and flow node, reasons embedded with 005's embedder (cached in `issue_failure_embeddings`), agglomerative clustering (cosine 0.25), clusters of 3 or more calls, at most 20 new issues per run, matched to existing issues at centroid similarity 0.85. New issues are named by one model call each. Billed once per run as `issues.detect`.
- Fixes: eight kinds, drafted by the model (`issues.draft_fix`, once per revision) or written by hand; every revision is kept. `fixes.apply_fix` is the one pure function that builds both the validation variant and the applied version.
- Validation: a control batch (published version) and a treatment batch (variant) over up to 20 affected calls and 10 guard calls. 008's completion hook queues `finalize_validation`, which waits for the simulated calls' evaluations (up to 20 minutes), pairs verdicts with 008's `pair_verdicts` and runs the keep rule (`validation_rule.py`, exact fractions). Evidence rows cannot change once written (trigger).
- Apply re-checks the evidence under row locks and records exactly the treatment batch's snapshot through 002 (`create_version`), release notes `Fix for <issue id>: <title>`. A tool description fix copies the tool when other agents use it.
- Crons: `sweep_issues` (every minute: stale detections fail after 15 minutes, finalized batches get their finalize job) and `audit_applied_issues` (daily 05:30, SC-001 hash audit, logs mismatches as errors).
- Setting (optional): `ISSUES_MODEL` (default `SIMULATOR_MODEL`). No new secrets. Quickstart fixtures: `uv run python -m app.dev.seed_issues --dsn ... --workspace ws_... --agent agt_...`.

## 11. Scheduled callbacks (spec 011)

- A caller who asks to be called back gets one: every single-prompt agent has a built-in
  `schedule_callback` tool (next to the built-in `end_call`), and its instructions carry the
  caller's current local date and time. The tool posts to `POST /v1/internal/calls/{id}/callbacks`;
  the API calls back the caller (inbound) or the dialled number (outbound), from the number the call
  used, with the call's own agent, and returns the time to say back ("tomorrow, Wednesday 4
  November, at 5:00 pm"). Inbound calls now run in the caller's number zone (`timezone` variable).
- Booking checks the do-not-call list and the calling hours at the booked time and refuses with a
  sentence the agent relays; outside hours it names the next allowed time so the agent can offer
  it. The time is never moved silently. Browser test calls and WhatsApp are refused; simulations
  get a mocked booking and store nothing.
- Cron `place_due_callbacks` (jobs worker, every minute at :20) dials due callbacks through 010's
  outbound path with idempotency key `callback:<id>`: blocks at dial time fail the callback and are
  logged as policy decisions, admission refusals (credit and so on) fail it with their code, a full
  workspace waits for the next run, and a callback not placed within 30 minutes fails as `missed`.
- Public API `GET/POST /v1/callbacks`, `GET /v1/callbacks/{id}`, `POST /v1/callbacks/{id}/cancel`.
  Web: Calls, Callbacks tab (`/calls/callbacks`) and a card in the source call's drawer.
- Migration `s011_0001`. No new settings or secrets.

## 12. Caller language and the default voice (spec 012)

- Default voice for new agents and the seed templates: ElevenLabs Multilingual v2 ($0.09/min,
  Flash v2.5 is $0.045). Existing agents keep their saved model. The Expressiveness slider maps
  to ElevenLabs settings in `worker/adapters/tts/elevenlabs.py`: 0 gives stability 0.9 and style 0,
  the default 0.9 gives stability 0.35 and style 0.3 (the expressive setting chosen by ear), 2
  gives 0.15 and 0.6, linear between; similarity 0.75 and speaker boost always; style only on
  Multilingual v2.
- Languages an agent offers: `services/api/app/caller_language/options.py` (speech recognition
  provider unchanged, model per language; English-only Flash v2 and Turbo v2 switch to their v2.5
  versions). The claim sends `language_options` and, on phone calls, `caller_language`.
- Worker: built-in `set_language` (`worker/tools/set_language.py`) next to `end_call` and
  `schedule_callback`; speech recognition and voice change at the next turn boundary through the
  segment override path, the reply-language line changes at once. A call that starts in a saved
  language translates the fixed greeting with the agent's model during session start and ring
  (`worker/language.py`), falling back to a model-written greeting after 4 s.
- API: switches are stored in `call_languages`, saved languages in `caller_preferences` (live
  phone calls only; never browser calls, WhatsApp or simulations). `GET/DELETE
  /v1/caller-preferences`, `GET /v1/calls/{id}/language`, internal
  `POST /v1/internal/calls/{id}/language`. Callbacks need nothing extra: they are outbound calls
  to the saved number.
- Agent setting `advanced.language_switching` (Basics tab, under Language). Migration `s012_0001`.
  No new settings or secrets.
