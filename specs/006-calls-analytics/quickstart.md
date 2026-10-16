# Quickstart: Calls and Analytics

Validates 006 end to end on a local stack. Assumes 001 and 003 are running locally and the
`make` targets from 001 exist (`make up`, `make migrate`, `make seed`).

## 1. Prepare

```bash
make up && make migrate
# Seeds 2 workspaces (ws_A, ws_B); in ws_A: 3 agents (one flow agent), 45 calls over the last
# 40 days across channels, statuses and sentiments, turn metrics, tool events, flow transitions,
# cost lines (including the 271 s reference call), and 2 simulation-origin calls.
python -m services.api.scripts.seed_006 --workspace ws_A --calls 45
export TOKEN_A=$(python -m services.api.scripts.dev_token --workspace ws_A)
export TOKEN_B=$(python -m services.api.scripts.dev_token --workspace ws_B)
```

## 2. Call history (US1)

```bash
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8000/v1/calls?page=1&page_size=20" | jq '.total, .total_pages'
# expect 45 and 3 (simulation calls hidden by default)

curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8000/v1/calls?channel=whatsapp&status=completed" | jq '[.items[].channel] | unique'
# expect ["whatsapp"]

curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8000/v1/calls?origin=live,test,simulation" | jq .total
# expect 47
```

In the browser: open `/calls`, tick 3 rows on page 1 and 2 on page 2, return to page 1, confirm
"5 selected"; select calls from two agents and confirm "Run simulation" is blocked.

## 3. Call detail and recording (US2)

```bash
CALL=$(python -m services.api.scripts.seed_006 --print reference_call)
curl -s -H "Authorization: Bearer $TOKEN_A" localhost:8000/v1/calls/$CALL | jq '.cost.header, .cost.surcharges'
# expect duration_s 271, billed_minutes ~4.52, avg_rate_per_min_usd ~0.106, one llm surcharge with multiplier 1.13
curl -s -H "Authorization: Bearer $TOKEN_A" localhost:8000/v1/calls/$CALL/recording | jq .expires_at
# expect a time at most 10 minutes ahead
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN_B" localhost:8000/v1/calls/$CALL/recording
# expect 404 (other workspace)
```

In the browser: `/calls?call=$CALL` opens the drawer; play, seek, download; confirm the failed
tool result is marked as an error and a turn without TTS timing shows "n/a".

## 4. Dashboard (US3)

```bash
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8000/v1/dashboard/stats?period=last_7_days&tz=Asia/Kolkata" | jq '.kpis.total_calls, (.series|length)'
# expect the seeded 7-day count and 7
curl -s -H "Authorization: Bearer $TOKEN_A" "localhost:8000/v1/dashboard/stats?period=custom&start_date=2026-10-10&end_date=2026-10-01"
# expect 422 "End date must be on or after start date"
```

## 5. Compare (US4)

Open `/calls/$CALL/compare?with=<second call id>`; confirm side-by-side alignment and highlighted
differing flow nodes. Request with a ws_B call ID and confirm "Call not found".

## 6. Analytics assistant (US5)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN_A" -H "Idempotency-Key: qs-006-0000000001" \
  -H "Content-Type: application/json" localhost:8000/v1/analytics/chat \
  -d '{"messages":[{"role":"user","content":"Cost by agent this month"}],"timezone":"UTC"}' | jq '.chart.chart_type, .computed_with'
# repeat the same request: same body returned, and the ledger shows one analytics_chat charge
pytest services/api/tests/integration/test_analytics_isolation.py -q   # hostile question suite
```

## 7. Voice copilot (US6)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN_A" localhost:8000/v1/voice-commands/interpret \
  -H "Content-Type: application/json" \
  -d '{"transcript":"show me failed calls from yesterday","visual_state":{"current_route":"/dashboard","current_datetime":"2026-10-16T10:00:00Z","timezone":"UTC","available_actions":[]}}' | jq
# expect action navigate, target /calls, params {status:["failed"], date_range:"yesterday"}
```

In the browser: hold Space on the dashboard, say the same command, confirm the filters appear as
chips. Deny microphone permission and confirm "Microphone blocked" plus the typing fallback.

## 8. Test suites

```bash
pytest services/api/tests/unit/calls services/api/tests/unit/dashboard services/api/tests/unit/analytics_chat services/api/tests/unit/voice_commands -q
pytest services/api/tests/contract -k "calls or recordings or dashboard or analytics_chat or voice_commands" -q
pnpm --filter web test -- routes/calls routes/dashboard app/assistant app/copilot
```
