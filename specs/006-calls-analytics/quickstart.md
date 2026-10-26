# Quickstart: Calls and Analytics

Validates 006 end to end on a local stack. Assumes 001 and 003 are running locally and the
`make` targets from 001 exist (`make up`, `make migrate`, `make seed`).

## 1. Prepare

```bash
make up && make migrate
# Sign up two users in the web app (or POST /v1/auth/register), note their workspace ids, then
# seed workspace A: 3 agents (one flow agent), 45 calls over the last 40 days across channels,
# statuses and sentiments, turn metrics, tool events, flow transitions, cost lines (including the
# 271 s reference call) and 2 simulation-origin calls. Workspace B stays empty.
cd services/api
uv run python -m app.dev.seed_calls --dsn postgresql://callwright:callwright@localhost:55432/callwright --workspace $WS_A --calls 45
export TOKEN_A=...   # access_token from POST /v1/auth/sign-in for user A
export TOKEN_B=...   # and for user B
```

## 2. Call history (US1)

```bash
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls?page=1&page_size=20" | jq '.total, .total_pages'
# expect 45 and 3 (simulation calls hidden by default)

curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls?channel=whatsapp&status=completed" | jq '[.items[].channel] | unique'
# expect ["whatsapp"]

curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls?origin=live,test,simulation" | jq .total
# expect 47
```

In the browser: open `/calls`, tick 3 rows on page 1 and 2 on page 2, return to page 1, confirm
"5 selected"; select calls from two agents and confirm "Run simulation" is blocked.

## 3. Call detail and recording (US2)

```bash
CALL=$(curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls?from_number=15551234567" | jq -r '.items[0].call_id')
curl -s -H "Authorization: Bearer $TOKEN_A" localhost:8100/v1/calls/$CALL | jq '.cost.header, .cost.surcharges'
# expect duration_s 271, billed_minutes ~4.52, avg_rate_per_min_usd ~0.106, one llm surcharge with multiplier 1.13
curl -s -H "Authorization: Bearer $TOKEN_A" localhost:8100/v1/calls/$CALL/recording | jq .expires_at
# expect a time at most 10 minutes ahead
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN_B" localhost:8100/v1/calls/$CALL/recording
# expect 404 (other workspace)
```

In the browser: `/calls?call=$CALL` opens the drawer; play, seek, download; confirm the failed
tool result is marked as an error and a turn without TTS timing shows "n/a".

## 4. Dashboard (US3)

```bash
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/dashboard/stats?period=last_7_days&tz=Asia/Kolkata" | jq '.kpis.total_calls, (.series|length)'
# expect the seeded 7-day count and 7
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/dashboard/stats?period=custom&start_date=2026-10-10&end_date=2026-10-01"
# expect 422 "End date must be on or after start date"
```

## 5. Compare (US4)

Open `/calls/$CALL/compare?with=<second call id>`; confirm side-by-side alignment and highlighted
differing flow nodes. Request with a ws_B call ID and confirm "Call not found".

## 6. Analytics assistant (US5)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN_A" -H "Idempotency-Key: qs-006-0000000001" \
  -H "Content-Type: application/json" localhost:8100/v1/analytics/chat \
  -d '{"messages":[{"role":"user","content":"Cost by agent this month"}],"timezone":"UTC"}' | jq '.chart.chart_type, .computed_with'
# repeat the same request: same body returned, and the ledger shows one analytics_chat charge
uv run pytest tests/integration/test_analytics_chat.py -q   # hostile question suite
```

## 7. Voice copilot (US6)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN_A" localhost:8100/v1/voice-commands/interpret \
  -H "Content-Type: application/json" \
  -d '{"transcript":"show me failed calls from yesterday","visual_state":{"current_route":"/dashboard","current_datetime":"2026-10-16T10:00:00Z","timezone":"UTC","available_actions":[]}}' | jq
# expect action navigate, target /calls, params {status:["failed"], date_range:"yesterday"}
```

In the browser: hold Space on the dashboard, say the same command, confirm the filters appear as
chips. Deny microphone permission and confirm "Microphone blocked" plus the typing fallback.

## 8. Test suites

```bash
cd services/api
uv run pytest tests/unit/calls tests/unit/recordings tests/unit/dashboard tests/unit/analytics_chat tests/unit/voice_commands -q
uv run pytest tests/contract/test_calls_contract.py tests/contract/test_dashboard_contract.py tests/contract/test_analytics_voice_contract.py -q
uv run pytest tests/integration/test_calls_read.py tests/integration/test_dashboard_aggregates.py tests/integration/test_voice_interpret.py -q
cd ../../apps/web && pnpm test -- routes/calls routes/dashboard app/assistant
```

## 9. Live walkthrough deltas (FR-034 to FR-041)

```bash
# Plus sign survives and formatting is ignored (expect the seeded +1555... calls)
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls?from_number=%2B1555" | jq .total
curl -s -H "Authorization: Bearer $TOKEN_A" --get --data-urlencode "from_number=1 (555)" localhost:8100/v1/calls | jq .total
# Calendar date in the viewer's timezone, inclusive end
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls?start_date=2026-10-01&end_date=2026-10-01&tz=Asia/Kolkata" | jq '[.items[].started_at]'
# CSV export of the same filtered list
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8100/v1/calls/export?channel=whatsapp&columns=call_id,started_at,status" | head -3
```

In the browser: rows per page offers 10, 20, 50, 100; hide Summary and reload (still hidden);
apply status, agent and own label and confirm three chips and a badge of 3; on the dashboard pick
"7d" and confirm every section reloads without an apply step, then press Refresh and confirm the
"Updated" time changes; in the Ask panel, force a 503 and confirm the retry message keeps the
question.
