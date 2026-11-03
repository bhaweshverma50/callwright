# Quickstart run: Voice Runtime (T110)

Run on 2026-11-03 on a laptop (macOS, Docker Desktop), branch `w6-verify` from main `2973a92`.
Local stack only: own database `callwright_w6v`, Redis db 10, API on 8150, jobs worker, web on
5230, `livekit-server` 1.13.3 on 7890 with Redis and the webhook pointed at the API. No vendor
keys: the voice worker ran the production agent server and job entry with the live benchmark's
fake STT, LLM and TTS (`tests/harness/bench/live_fakes`), now documented in section 2.

Legend: **pass** ran as written; **drift** ran after a doc or code fix (listed); **partial** part
of the step ran; **not run** with the reason.

| Section | Result | Notes |
|---|---|---|
| 1 Prerequisites | drift | `psql $DATABASE_URL` cannot use the SQLAlchemy URL from `.env` (and the app role sees no rows through RLS): the doc now exports an owner URL. livekit-server with `keys: {devkey: secret}` logs "secret is too short" and runs. |
| 2 Run | drift | API, jobs worker, web as written. Voice worker with keys not run (no keys); the fake-vendor worker command was added. |
| 3 Browser test call | pass | `scripts/e2e-call.mjs` (Playwright, fake microphone) on the clinic template: greeting at 0.26 s, a caller turn and a reply, End call; row `web`, `completed`, `user_hangup`, `turn` rows per reply. API path: greeting "Hi Priya" in 41 ms. |
| 3 API only | drift | `lk room join --token` does not exist in lk 2.16; replaced with `--api-key/--api-secret --identity <caller> <room_name>`. |
| 3 Microphone blocked | partial | Headless Chrome reports no microphone rather than a blocked one: "No microphone found ... No call was created", no `POST /v1/sessions/web-call`. The blocked wording is covered by `WebCallPanel.test.tsx`. Doc button name fixed ("Start test call"). |
| 4 Concurrency | pass | limit 1, second request 429 `concurrency_limit` with a `call_id`. |
| 4 Credit | drift | There is no "001 admin tool" for adjustments; the doc now has a `post_transaction` snippet. Balance 0 gives 402 `insufficient_credit`. |
| 4 Max duration, silence | pass | `max_duration_s=30`, silence 60: `max_duration_reached` at 30 s. Silence 10: `inactivity` at 16 s (after the check-in). |
| 4 Worker crash | drift | Killed the worker mid-call: `error`, diagnostic `heartbeat_lost` after about 70 s, then `completed` by the pipeline (doc said `ended`). |
| 5 Harness scenarios | pass | 9 passed. |
| 5 Auto STT | partial | `call_costs` STT line is Deepgram `nova-2` at 0.0058 per minute for a Hindi agent on Auto; `usage->'stt'` stays `[]` with the fake STT (needs a Deepgram key). `test_auto_stt.py` 13 passed. |
| 6 Pipeline steps, replay | **code fix** | `python -m app.calls.jobs replay <call_id>` reset every step and then blocked on `LookupError: agent version ... is not available`: the CLI never registered 002's agent versions (the API and jobs worker do). Fixed in `app/calls/jobs.py` (registers agent versions and the quality port like the worker), test `tests/unit/test_replay_cli.py`. After the fix: all steps `done`, one credit transaction. |
| 6 Recording available | not run | Needs the egress service and MinIO; without it the call shows `recording_status=failed` and warning `recording_unavailable` as documented. |
| 6 Recording off | pass | workspace default off: `f | workspace | not_recorded | null`, turns recorded, no pipeline warning. Agent override `on` records the next call (`agent`, then `failed` without egress). |
| 7 Webhooks | drift + **code fix** | The agent editor refused `http://localhost:9009/hook` with `private_address` even with `WEBHOOKS_ALLOW_PRIVATE=true` (002's validator ignored the flag that 003's delivery honours). Fixed in `app/agents/webhook_url.py` (dev only; production already refuses the flag). Then `localhost` failed with `connection_error`: it resolves to `::1` first and the receiver listens on IPv4; doc now uses `127.0.0.1`. Result: `call_started` and `call_ended` 500, 500, then 200; `call_analyzed` 200. |
| 8 Voicemail and keypad | **code fix** | Harness 3 passed. A keypad `1234#` (published as DTMF over LiveKit) produced two caller lines, `1234` from `keypad` and an echo `1234` from `voice`: the session's `generate_reply(user_input=...)` adds a user item that the transcript recorded again. Fixed in `worker/entry.py` (the echo is skipped once), test in `tests/unit/test_live_call.py`. After the fix: one caller turn. |
| 9 Harness and benchmark | pass | Harness 122 passed in 29 s. Fake benchmark exit 0. Live benchmark against the local server (4 calls, 2 at once): p50 749 ms, p95 1392 ms, no missed turns, exit 0 (`--url` documented). |

Not run anywhere: real vendors (Deepgram, OpenAI or Azure OpenAI, ElevenLabs) and recording
upload, both need keys or the egress service.
