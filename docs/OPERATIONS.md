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
cd ~/callwright
ACCOUNT=bhaweshverma50@gmail.com; PROJECT=callwright-dev; ZONE=asia-south1-a
TAG=$(git rev-parse --short HEAD)

# API (add `setup` first when a new secret was added; add `migrate` when migrations changed)
deploy/cloudrun/deploy.sh $PROJECT $ACCOUNT build api
# Voice worker image (only when services/voice-worker changed)
deploy/cloudrun/deploy.sh $PROJECT $ACCOUNT build-voice

# VM: copy compose files when deploy/vm changed, then roll the workers and prune old images
gcloud compute instances start callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT
gcloud compute scp --recurse deploy/vm/docker-compose.yml deploy/vm/render-env.sh \
  deploy/vm/roll-voice.sh deploy/vm/livekit.yaml.tmpl deploy/vm/sip.yaml.tmpl deploy/vm/sip-tls.yaml.tmpl deploy/vm/lab-pbx \
  callwright-rtc:/opt/callwright/ --zone $ZONE --account $ACCOUNT --project $PROJECT
gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
  "cd /opt/callwright && CW_API_IMAGE=asia-south1-docker.pkg.dev/$PROJECT/callwright/api:$TAG \
   CW_VOICE_IMAGE=asia-south1-docker.pkg.dev/$PROJECT/callwright/voice-worker:$TAG ./render-env.sh \
   && sudo docker compose pull worker textsim && sudo docker compose up -d worker textsim \
   && sudo ./roll-voice.sh && sudo docker image prune -af"

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

## 13. Live calls and refresh (2026-11-03)

- `GET /v1/calls/live` (contract `specs/006-calls-analytics/contracts/calls.yaml`): calls queued,
  ringing or in progress, live and test origins only, newest 50 plus a total `count`, each with
  agent, channel, direction, numbers, `ringing_at`, `connected_at` and the latest caller or agent
  line; `server_time` lets clients tick durations on the server clock. Two indexed reads under
  RLS, no Redis, so polling it never wakes the VM. Call list items and details also carry
  `connected_at` now. No migration.
- Web: one shared query (`api/live.ts`) feeds the sidebar's Calls badge, the dashboard's
  "Live now" card (a quiet line when nothing is on air) and the rows pinned above Call History.
  It polls every 3 s while anything is on air and every 15 s otherwise, only in a visible tab.
  `useLiveCallSync` in the shell turns its changes into targeted refreshes: a new call refreshes
  the call lists, an answered or ended call refreshes that call's detail and transcript, an
  ended call refreshes the dashboard, balance, transactions, usage and callbacks, again 20 s
  later once pricing and analysis land.
- No server push exists (the only websocket is the copilot's speech to text), so everything is
  polling keyed on status; `refetchOnWindowFocus` stays off app-wide as before.
- Mock mode: `?live=3` (or `seedMockLiveCalls(3)` from the console) puts calls on air: one rings
  and is answered 12 s later, the others are live with transcripts that grow a line every 4 s.
  Without it the workspace is quiet. Example: `/login?seed&live=3`.

Refresh audit:

| Place | Changes on its own | Before | After |
|---|---|---|---|
| Sidebar, Calls item | calls start and end | nothing | live badge (count and on-air dot) from the shared live query |
| Dashboard | calls on air | nothing | "Live now" card, 3 s while on air, 15 s idle; a row opens the call drawer in place |
| Dashboard figures (stats, quality, agent health) | every finished call and evaluation | only on Refresh or reload | every 60 s, and when a call ends (again 20 s later) |
| Dashboard setup sequence | the first call | cached 60 s, never refetched | every 30 s while empty, at once when a call starts |
| Call History | ringing, answer, hang-up, processing | 4 s while active, 15 s idle (efb8361) | plus calls on air pinned on top, "On air" pill and ticking duration in rows, list refetched the moment a call starts or ends |
| Call drawer | ringing to live to ended to processing | polled only in progress and processing; a ringing call never updated | 3 s while queued, ringing or live; 4 s while processing or the recording uploads; ticking duration; no cost or recording block while on air |
| Drawer transcript | new lines during the call | polled only in progress; the final transcript was not fetched after hang-up | 3 s while ringing or live, refetched on every status change, follows the newest line unless the reader scrolled up |
| Drawer latency and flow path | per-turn latency, node transitions | fetched once (flow cached 5 min) | 3 s while live, refetched on status change |
| Drawer analysis, checks, callback card | post-call results, a callback booked mid-call | opened during the call: checks and callbacks never refetched | refetched on every status change, then their own running polls |
| Balance chip, billing transactions and usage | call charges | balance every 60 s; transactions and usage static | refreshed when a call ends and 20 s later |
| Callbacks tab count | the callback cron | cached 30 s, no poll | every 30 s |
| Outbound call dialog | the placed call rings | nothing | live list and call list refetched at once |
| Browser test call | the caller's own call | badge on the next idle poll | live list refetched on connect and on hang-up |

Already right and unchanged: knowledge ingestion (3 s while processing), phone numbers and
WhatsApp channels while settling (5 s), simulations, batches, scorecards and comparison (3 s
while active), test runs (3 s), issue detection and validation (2 s), call analysis and
evaluations (3 s while running), callback lists (10 s while one is open). Left static on
purpose: review queue (reshuffling under a reviewer is worse), calibration, datasets, agents,
tools and flows (they change through the user's own mutations, which invalidate), analytics chat
(a synchronous request), playground (its own live session).

## 14. Flow callbacks, caller language and endings (2026-11-03)

From a lab SIP call to a flow agent: the caller said "I'm getting a call. Can you call me in five
minutes?" and the agent answered "Thanks for calling. Goodbye." and hung up; no callback was
booked and the job then hung for a minute on shutdown.

- Flow agents get the built-ins: every conversational node has `schedule_callback` and (when the
  claim offers more than one language) `set_language` next to its own tools and transitions, with
  the same callback rule (caller's local time), language rule and voice style as single-prompt
  agents. The ending rule for flow nodes says to end through the flow's own step (a transition to
  an End node, or an end_call tool) after confirming the next step; flows get no built-in end_call.
  The API now sends `language_options` for flow agents too. A language switch on a flow rebuilds
  the node the call is on at the turn boundary (it used to rebuild the entry agent, restarting the
  flow); nodes entered later keep the reply language, and the caller's language wins over a node's
  own voice and speech recognition. Text simulations exercise both (mocked booking, instructions
  only for language).
- End nodes: an empty message or the old stock line "Thanks for calling. Goodbye." makes the agent
  say a short goodbye in its own words that fits the call (confirming a booked callback or next
  step). The call's model writes it while the reply that took the transition plays; the wait after
  that reply is at most 1.5 s (4 s overall) before the stock line is said instead, and nothing more
  is said when the reply already ended with a goodbye. A message the builder wrote is spoken word
  for word. New flows default to an empty End message (API starter, web flow model, editor copy
  "Leave empty to let the agent say goodbye in its own words"); the `W_END_NO_MESSAGE` warning is
  gone.
- Callers who have to go: the ending rule (single-prompt and flows) says a caller who is
  interrupted (another call, a meeting, "hold on") has not ended the conversation; ask in one short
  question whether they want a call back, and book it with schedule_callback when they ask. Replayed
  with gpt-5.1 on "I'm getting a call." alone: 0 of 8 hang-ups (single-prompt and flow), against 7
  of 8 before; with "... Can you call me in five minutes?" 3 of 3 booked.
- Hang-up guard: speech recognition can finalise "I'm getting a call." as its own turn while the
  caller goes on. end_call and a transition into an End node first let the reply play, then wait
  (at most 2 s) until no words were transcribed for 1 s; a caller still talking is not hung up on
  (end_call answers "not ended", the transition is not taken). Normal turns are untouched: LiveKit's
  endpointing (fixed `min_delay` from responsiveness, the semantic turn detector or STT end of turn)
  is unchanged, so the latency budgets of spec 003 hold. Voice activity without transcribed words
  (line noise) never keeps a call open past the 2 s.
- Shutdown hang (root cause): hang-ups mostly come from inside the session (end_call, a flow End
  node, transfers). `LiveCall.end` awaited `AgentSession.aclose()` there, and the close waits for
  every running speech task, including the tool that was waiting for it. LiveKit cancelled the tool
  after its interruption timeout ("speech not done in time after interruption"), the close never
  finished, the room was not deleted and `ctx.shutdown` never ran; at job shutdown
  `AgentSession.aclose()` timed out after 60 s and the process was killed. It affected single-prompt
  end_call as well (the earlier bench repro hung the same way). The close now runs in its own task
  after the hang-up returns (so end_call's own `tool_call` event, which used to be lost, is posted
  before the final status), with a 10 s cap on the session close. Regression test
  `test_end_call_from_inside_the_session_closes_it_promptly`; real-vendor bench calls now end in
  about 2.5 s.
- Deploy: API (`deploy.sh ... build api`, no migration: starter default, validation, language
  options for flows), voice image (`build-voice`, roll `voice` and `textsim`), Vercel (End node
  editor). No new settings.

## 15. Signup abuse protections

Anyone can script signups and spend each new workspace's trial credit on paid vendor calls. Four
protections exist, all off (or harmless) until configured. Set secrets in Secret Manager (name =
env var, `setup` binds them, `deploy.sh` mounts optional ones that exist) and plain settings in the
shell that runs `deploy.sh ... api`.

- **Daily trial-credit budget**: `TRIAL_CREDIT_DAILY_BUDGET_USD=25` caps the trial credit granted
  per UTC day across all new workspaces. Past the cap, new workspaces start at $0 (logged). Redis
  down while this is set also grants nothing. Unset or 0 means unlimited. No migration.
- **Captcha (Cloudflare Turnstile)**: create a widget in the Cloudflare dashboard (Turnstile), put
  its secret in the `TURNSTILE_SECRET_KEY` secret, and set `VITE_TURNSTILE_SITE_KEY` to the site key
  in Vercel (build-time, so redeploy the web app). `POST /auth/register` then needs `captcha_token`
  (400 `captcha_failed`; 503 if Cloudflare is unreachable). Unset means no check.
- **Real verification emails**: `SMTP_HOST` (for example `smtp.gmail.com`), `SMTP_PORT` (587,
  STARTTLS), `SMTP_USERNAME`, `SMTP_FROM`, and the `SMTP_PASSWORD` secret. A Gmail app password
  works (Google account, 2-step verification, App passwords). The local IdP then emails each
  verification and reset link as well as keeping the dev outbox. Send failures are logged with the
  address masked and never fail registration; the user can press resend.
- **Disposable domains**: registration refuses throwaway email domains
  (`BLOCK_DISPOSABLE_EMAIL`, on by default; list in `services/api/app/auth/disposable_domains.txt`,
  refreshed monthly by the `disposable-domains` workflow). `EXTRA_BLOCKED_EMAIL_DOMAINS=a.com,b.com`
  adds more without a code change.

### Sign in with Google

"Continue with Google" on the sign-in and register pages (also how a new account is created with
Google). Only with `AUTH_PROVIDER=local`. It is on when both `GOOGLE_SIGNIN_CLIENT_ID` and
`GOOGLE_SIGNIN_CLIENT_SECRET` are set; these are separate from the Drive connector's
`GOOGLE_OAUTH_*`. Google verifies the email, so this path skips the captcha and the disposable
domain check but keeps the per-IP rate limit (`GOOGLE_SIGNIN_RATE_LIMIT_PER_HOUR`, 60). No migration.

1. Google Cloud Console, project `callwright-dev`: APIs and Services, OAuth consent screen. User
   type External. Scopes: `openid`, `email` and `profile` only (they need no Google verification).
   While the app is in Testing, only listed test users can sign in; publish it to let anyone in.
2. Credentials, Create credentials, OAuth client ID, type Web application. Authorized redirect URIs:
   `https://callwright-one.vercel.app/auth/google/callback` and
   `http://localhost:5180/auth/google/callback` (the API builds it from `WEB_BASE_URL`).
3. Put the client secret in Secret Manager as `GOOGLE_SIGNIN_CLIENT_SECRET` (`deploy.sh ... setup`
   binds it; `deploy.sh ... api` mounts it once it exists). Export the client id in the shell that
   runs the API deploy: `GOOGLE_SIGNIN_CLIENT_ID=... deploy/cloudrun/deploy.sh $PROJECT $ACCOUNT build api`.
   It is dropped from the service env when not exported, like the SMTP values.

An email that someone registered with a password but never verified is taken over by the Google
sign-in: the account is confirmed, its password replaced and its sessions and pending links revoked.
`/v1/auth/config` tells the web app whether to show the button; no web redeploy is needed.

Keep `AUTH_AUTO_VERIFY_EMAIL=true` until SMTP is confirmed working (register, then check the
inbox). Only then set `AUTH_AUTO_VERIFY_EMAIL=false`; with it off, an account cannot sign in or
get its trial credit until the emailed link is opened. The deploy script still sets it to true,
so change the line in `step_api` at that point.

## 16. Google connections and Drive knowledge sync (spec 022)

Knowledge bases can sync from a Google Drive folder or shared drive. A workspace connects a Google
account once on Settings > Connections (read-only Drive, plus Google Sheets access requested now and
held for the Sheets tool). Calls only ever search the synced copy.

Settings (all three OAuth values empty turns the feature off; the routes return 503
`connector_unavailable`):

| Variable | Where | Value |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Secret Manager (optional) | OAuth client id |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Secret Manager (optional, may be `enc:v1:`) | OAuth client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | Secret Manager (optional) | `https://<web app>/settings/connections/callback` |
| `CONNECTORS_DRIVE_MODE` | env | `live` (default) or `fake` (in-memory Drive for tests and demos; refused in prod) |
| `CONNECTORS_WORKSPACES` | env | Beta allowlist: comma-separated workspace ids that may connect Google and add sources; empty (default) is everyone |
| `CONNECTORS_SYNC_PAUSED` | env | Kill switch: `true` stops scheduled syncs (Sync now and searches keep working) |

Google Cloud setup (one time, per project):

1. Create a project; enable the Google Drive API and the Google Sheets API.
2. Google Auth Platform (OAuth consent screen): app name, support email, audience External,
   publishing status Testing, add test users.
3. Data access: scopes `openid`, `.../auth/userinfo.email`, `.../auth/drive.readonly`
   (restricted) and `.../auth/spreadsheets` (sensitive).
4. Clients: Web application; authorized JavaScript origin of the web app; redirect URI
   `<web app>/settings/connections/callback` (local: `http://localhost:5180/settings/connections/callback`).
5. Copy the client id and secret into the settings above.

Known behaviour:

- While the project is in Testing, only listed test users can connect, and Google expires their
  refresh tokens after 7 days. The connection then shows "Revoked"; Reconnect fixes it. Both
  scopes need Google's verification before general release.
- Syncs run on the jobs worker (cron `sync_due` every minute, job `sync_source`); the worker needs
  the same three Google settings as the API.
- A sync job has a 25-minute timeout and refreshes its claim every minute; a claim silent for 10
  minutes is stale and the next sync takes over.

Metrics: each finished run logs `drive sync finished` with `metric=kb_sync_run` and `status`,
`failure_reason`, `attention`, `duration_s` and counts. Suggested log-based alerts: `status=failed`
by `failure_reason` above its usual rate; `failure_reason=google_unavailable` spikes (Google 429s
or an outage); p95 `duration_s` above 15 minutes; any `attention=mass_archive` (an owner must
decide); a jump in `attention=access_lost`.

Runbook:

- **Pause all scheduled syncs now** (Google incident, quota exhausted, bad deploy):
  `redis-cli -u "$REDIS_URL" SET connectors:sync_paused 1`; resume with `DEL connectors:sync_paused`.
  For a lasting pause set `CONNECTORS_SYNC_PAUSED=true` on the worker. Due sources run once resumed.
- **A source is stuck on "Syncing"**: its claim expires 10 minutes after the last heartbeat and the
  next scheduled sync or Sync now takes over; the stale run is recorded as failed. Check the worker
  logs for its `run_id` (`drive sync finished`, or a crash or cancellation) before forcing anything.
  To release it at once: `UPDATE kb_sources SET running_run_id = NULL, running_since = NULL WHERE id = '<ksrc_...>';`
- **Every connection shows "Revoked"**: usually the Testing-mode 7-day expiry, or the OAuth client
  secret was rotated or the client deleted. Check the client in the Cloud console and the API logs
  for `invalid_grant`; owners then press Reconnect. Sources resume by themselves after a reconnect,
  and nothing was archived while access was lost.
- **A sync is held for a mass archive**: only the knowledge base owner should decide (Archive them
  or Keep them on the source). Do not confirm on their behalf.
