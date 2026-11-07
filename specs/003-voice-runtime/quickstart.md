# Quickstart: Voice Runtime

**Feature**: 003-voice-runtime | **Plan**: [plan.md](./plan.md)

How to run the runtime locally and check each user story. Commands assume the repository root.

## 1. Prerequisites

- Docker (Postgres 16 with pgvector, Redis 7, MinIO for S3)
- `livekit-server` 1.8+ and `livekit-cli` (`lk`) for a local media server, or a LiveKit Cloud
  project
- Python 3.12 with `uv`; Node 20 with `pnpm`
- Features 001 (accounts, billing, pricing) and 002 (agents, versions) migrated and seeded

```bash
docker compose up -d postgres redis minio
livekit-server --dev --bind 0.0.0.0          # API key "devkey", secret "secret", ws://localhost:7880
```

Environment (`services/api/.env` and `services/voice-worker/.env`):

```bash
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
CALLWRIGHT_INTERNAL_API_URL=http://localhost:8100/v1/internal
CALLWRIGHT_SERVICE_TOKEN=dev-service-token
RECORDINGS_BUCKET=callwright-recordings
CREDIT_GRACE_USD=0.50
WORKER_AGENT_NAME=callwright-voice
LIVEKIT_MODE=live                    # API only: fake records rooms and dispatches in memory
# Vendor keys only for real-vendor runs (not needed for the offline harness)
DEEPGRAM_API_KEY=...  AZURE_OPENAI_API_KEY=...  ELEVEN_API_KEY=...
```

Local egress needs the `livekit/egress` container pointed at MinIO; without it recordings are
marked `failed` (pipeline warning `recording_unavailable`) and every other story still works.

`psql $DATABASE_URL` below means a plain Postgres URL as the owner role, which sees every row
(`DATABASE_URL` in `.env` is a SQLAlchemy URL for the RLS-bound app role and psql refuses it):

```bash
export DATABASE_URL=postgresql://callwright:callwright@localhost:55432/callwright
```

## 2. Run

```bash
cd services/api && uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8100              # API
uv run arq app.worker.WorkerSettings                          # jobs (pipeline, webhooks, reaper)
cd ../voice-worker && uv run python -m worker.entry dev       # voice worker (vendor keys)
cd ../../apps/web && pnpm dev                                 # SPA on http://localhost:5180
```

Point the media server's webhooks at the API by starting `livekit-server` with a config file
containing `webhook: {api_key: devkey, urls: ["http://localhost:8100/v1/livekit/webhook"]}`
(with `keys: {devkey: secret}` it logs "secret is too short" and runs anyway).

Without vendor keys, run the voice worker with fake STT, LLM and TTS instead (the production
agent server and job entry; the caller's speech is detected by energy, every caller turn reads
"Hello?" and every reply is "Sure, I can help with that."). Calls then work end to end, but
vendor usage (`usage->'stt'`) stays empty:

```bash
cd services/voice-worker && PYTHONPATH=. uv run python -c "
import asyncio
from worker.entry import create_server
from worker.settings import WorkerSettings
from tests.harness.bench.live_worker import bench_job_entry
if __name__ == '__main__':
    asyncio.run(create_server(WorkerSettings(), entrypoint=bench_job_entry).run(devmode=True))"
```

## 3. User Story 1: browser test call

1. Sign in, open an agent whose greeting is `Hi {{customer_name}}`, go to `/agents/<id>/testing`.
2. Click "Start test call" (fill `customer_name` with `Priya` when asked). Expect the greeting within 3 seconds.
3. Talk for three turns, click "End call".
4. Check the call:

```bash
psql $DATABASE_URL -c "select id, channel, status, disconnect_reason, billable_seconds,
  latency_stats->>'e2e_p50_ms' p50 from calls order by created_at desc limit 1;"
psql $DATABASE_URL -c "select turn_index, stt_final_ms, llm_ttft_ms, tts_ttfb_ms, e2e_ms
  from call_events where call_id = '<call_id>' and type = 'turn' order by seq;"
```

Expect `web`, `completed` (after the pipeline), `user_hangup`, one `turn` row per agent reply.

API only:

```bash
curl -s -X POST localhost:8100/v1/sessions/web-call \
  -H "Authorization: Bearer $JWT" -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"agt_...","version":"draft","dynamic_variables":{"customer_name":"Priya"}}'
# then join the returned room_name as the caller (lk mints its own token):
lk room join --url ws://localhost:7880 --api-key devkey --api-secret secret \
  --identity caller --auto-subscribe <room_name>
# stop it (Ctrl-C) to hang up: the call ends user_hangup
```

A scripted browser call with a fake microphone (sign-up needs `AUTH_AUTO_VERIFY_EMAIL=true`):

```bash
cd apps/web && node scripts/e2e-call.mjs ../../services/voice-worker/tests/harness/bench/fixtures/turn_4.wav /tmp/e2e
```

Microphone blocked (US1.7, FR-047): in the browser site settings block the microphone, click
"Start test call": the panel explains how to allow it, the network panel shows no
`POST /v1/sessions/web-call`, and no new row appears in `calls`. (Headless Chrome with no
microphone shows the "No microphone found" variant of the same notice.)

## 4. User Story 2: admission and endings

```bash
# concurrency: set limit to 1, start one call, request a second
psql $DATABASE_URL -c "update workspaces set concurrency_limit = 1 where id = 'ws_...';"
# second POST /v1/sessions/web-call returns 429 with type .../concurrency-limit and a call_id
# credit: post an adjustment that brings the balance to 0, then request a call: 402
uv run --directory services/api python -c "
import asyncio
from app.billing.service import latest_seq_and_balance, post_transaction
from app.core.config import get_settings
from app.core.db import Database
async def main(ws):
    s = get_settings(); db = Database(s.database_url, s.database_admin_url, pool_size=1)
    async with db.transaction(workspace_id=ws) as session:
        _, balance = await latest_seq_and_balance(session, ws)
        await post_transaction(session, workspace_id=ws, type='adjustment', amount_usd=-balance, description='quickstart')
    await db.dispose()
asyncio.run(main('ws_...'))"
# restore with a positive adjustment (or add funds through the test checkout)
```

Max duration and silence: set `max_duration_s = 30` on a draft, start a test call, stay
silent; the call ends with `inactivity` if `end_on_silence_s` is lower, else with
`max_duration_reached` at about 30 seconds.

Worker crash: start a call, kill the voice worker process; within about 75 seconds the reaper
ends the call with reason `error` and diagnostic `heartbeat_lost` (then the pipeline moves it to
`completed`).

## 5. User Story 3: configured behaviour

Run the harness scenarios that cover it (no vendors needed):

```bash
cd services/voice-worker
uv run pytest tests/harness -k "interruption or responsiveness or pronunciation or background or segment_override"
```

Auto speech recognition (US3.7, FR-045): set an agent's language to `hi`, STT `deepgram` with
model Auto, run a test call, then:

```bash
psql $DATABASE_URL -c "select usage->'stt' from calls order by created_at desc limit 1;"
# [{"provider":"deepgram","model":"nova-2",...}]; the call_costs STT line uses rate 0.0058
uv run --directory services/api pytest tests/unit/test_auto_stt.py -q
```

## 6. User Story 4: pipeline and recording

```bash
psql $DATABASE_URL -c "select step, status, attempts from call_pipeline_steps where call_id='<id>';"
# replay every step: should not create a second charge
uv run python -m app.worker replay <call_id>
psql $DATABASE_URL -c "select count(*) from credit_transactions where call_id='<id>';"   # expect 1
```

Recording: `recording_status = available` and the object
`recordings/<workspace_id>/<call_id>.mp4` exists in MinIO with two audio channels.

Recording off (spec FR-043, FR-044). The workspace default is 001's
`workspaces.recording_default`; the agent override is 002's `advanced.recording`
(`inherit`, `on`, `off`). Turn the workspace default off and place a call on an agent that
inherits it:

```bash
psql $DATABASE_URL -c "update workspaces set recording_default = false where id = '<workspace_id>';"
# place a browser test call (section 3), end it, then:
psql $DATABASE_URL -c "select recording_enabled, recording_setting_source, recording_status, egress_id from calls where id = '<id>';"
# expect: f | workspace | not_recorded | (null)
psql $DATABASE_URL -c "select count(*) from call_events where call_id = '<id>' and type = 'turn';"   # expect > 0
```

No object exists under `recordings/<workspace_id>/<call_id>.mp4`, the call is `completed` with
no pipeline warning, and the `call_analyzed` delivery shows `recording_status: not_recorded`
and `recording_url: null`. Setting the agent's override to `on` records the next call even with
the workspace default off. Restore the default with `recording_default = true`.

## 7. User Story 5: webhooks

Start a receiver that fails twice then succeeds:

```bash
uv run --directory services/api python tests/integration/tools/flaky_receiver.py --fail 2 --port 9009
```

Set the agent's webhook URL to `http://127.0.0.1:9009/hook` (plain HTTP and local addresses
need `WEBHOOKS_ALLOW_HTTP=true` and `WEBHOOKS_ALLOW_PRIVATE=true` on the API and the jobs
worker, refused in production; use the IP: `localhost` resolves to `::1` first and the receiver
listens on IPv4 only), place a call, then:

```bash
curl -s "localhost:8100/v1/webhooks/deliveries?call_id=<id>" -H "Authorization: Bearer $JWT" | jq
```

Verify a signature (receiver side):

```python
import hmac, hashlib, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = [p.split("=", 1) for p in header.split(",")]
    t = int(next(v for k, v in parts if k == "t"))
    if abs(time.time() - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")
```

## 8. User Story 6: voicemail and keypad

```bash
uv run --directory services/voice-worker pytest tests/harness -k "voicemail or dtmf"
```

In a browser test call with keypad input enabled (`advanced.dtmf.enabled`), the panel's keypad
sends digits; pressing `1234#` produces one caller turn `1234` (source `keypad`) in the
transcript.

## 9. User Story 7: harness and benchmark

```bash
cd services/voice-worker
uv run pytest tests/harness                       # offline, no network, under 5 minutes
uv run python -m tests.harness.bench.benchmark    # fake mode: harness timing model, no network
# live mode: real WebRTC rooms on a local media server, worker with fake STT/LLM/TTS
docker run --rm -d --name lk-bench -p 7880:7880 -p 7881:7881 -p 7882:7882/udp \
  livekit/livekit-server --dev --bind 0.0.0.0
uv run python -m tests.harness.bench.benchmark --mode live [--url ws://localhost:7880] \
  [--calls 4 --concurrency 2] [--details /tmp/turns.json]
docker stop lk-bench
```

Both modes print p50 and p95 `e2e_ms` and exit non-zero when p50 > 800 ms, p95 > 1,500 ms or
either regresses more than 10% against the baseline (`tests/harness/bench/baseline.json` for
fake mode, `baseline_live.json` for live mode; `--update-baseline` rewrites it). Live mode
measures `e2e_ms` at the caller and also fails on missed turns or event contract violations.
Real vendors are not wired into live mode yet: that needs `DEEPGRAM_API_KEY`,
`AZURE_OPENAI_API_KEY` (with endpoint and API version) and `ELEVEN_API_KEY` plus a switch that
skips the fake vendor registry (see `tests/harness/bench/live.py`).
