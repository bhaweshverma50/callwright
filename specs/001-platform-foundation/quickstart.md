# Quickstart: Platform Foundation

How to verify feature 001 end to end on a developer machine. Each step names the spec item it
proves. Commands assume the repository root.

## 0. Prerequisites

- Docker, Python 3.12 with `uv`, Node 20 with `pnpm`
- Supabase CLI (`supabase start` for local auth) or a hosted dev project
- Stripe CLI logged in to a test-mode account

```bash
docker compose up -d postgres redis minio
supabase start                                  # prints the local auth URL and keys
cp services/api/.env.example services/api/.env  # fill SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_* (test mode)
cd services/api && uv sync && uv run alembic upgrade head && cd -
uv run --directory services/api uvicorn app.main:app --reload --port 8000 &
uv run --directory services/api arq app.core.jobs.WorkerSettings &
stripe listen --forward-to localhost:8000/v1/webhooks/stripe   # copy the whsec_ into STRIPE_WEBHOOK_SECRET
cd apps/web && pnpm install && pnpm dev                         # http://localhost:5173
```

## 1. Automated checks first

```bash
uv run --directory services/api pytest tests/unit tests/contract -q
uv run --directory services/api pytest tests/integration -q
cd apps/web && pnpm test && pnpm exec playwright test
python scripts/assemble_contracts.py --check    # fails if contracts/openapi.yaml is stale
```

Expected: all green. The money tests that must pass (SC-004, SC-005):
- `tests/unit/pricing/test_engine.py::test_reference_call_prices_to_0_477`
- `tests/unit/pricing/test_engine.py::test_4_2_second_call_bills_5_seconds`
- `tests/integration/billing/test_stripe_webhook.py::test_replayed_event_credits_once`

## 2. Sign up and land in a workspace (US1, FR-001 to FR-005)

1. Open `http://localhost:5173/register`, register `ops+1@example.com` with a 10+ character password.
2. Open the local mail catcher (Supabase Inbucket, `http://localhost:54324`), click the link.
3. You land on `/dashboard`: the top-bar chip shows **$5.000** and links to `/billing`; the rail is
   collapsed (hover shows labels) and, expanded, lists Dashboard, Agents, Calls, Quality (Datasets,
   Simulations), Feedback (Review, Calibration, Issues), Channels, Knowledge, Billing.
4. In the browser network panel, the first load shows only identity and balance reads: no token
   or session requests for the voice copilot or other optional features (FR-020).

API check:

```bash
TOKEN=$(curl -s localhost:8000/v1/auth/sign-in -H 'content-type: application/json' \
  -d '{"email":"ops+1@example.com","password":"correct-horse-9"}' | jq -r .access_token)
curl -s localhost:8000/v1/me -H "authorization: Bearer $TOKEN" | jq
# user.email_verified = true, workspace.concurrency_limit = 5, balance_usd = "5.000000"
```

Throttling (US1.2): send 5 wrong passwords, then a 6th:

```bash
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/v1/auth/sign-in \
  -H 'content-type: application/json' -d '{"email":"ops+1@example.com","password":"wrong-pass-x"}'; done
# 401 x5 then 429 with retry_after_s in the body
```

Sign-out everywhere (US1.3): open `/billing` in two tabs, sign out in one; the other redirects to
`/login?next=/billing` within a second, and the old token gets `401` from `/v1/me`.

Password reset (US1.4): `/forgot-password`, follow the email link, set a new password; using the
same link again shows "link expired or already used".

Settings (US1.5, FR-017): open the user menu, choose Settings, rename the workspace, turn the
recording default off, save. Reload: both values persist; `GET /v1/me` shows
`workspace.recording_default = false`. An empty name shows a field error and saves nothing.

Not found and id hygiene (US1.6, US1.7, FR-018, FR-019):

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/v1/agents/not-an-id -H "authorization: Bearer $TOKEN"
# 404 (problem+json, code not_found), never 5xx
```

Open `http://localhost:5173/no-such-page`: the shell shows "page not found" with a link to the
dashboard. Open an address with an unknown record id: the page names the missing record kind
with no status code text.

Leave guard (US1.9, FR-021): type into any create form, then press reload: the browser asks to
stay or leave.

## 3. Top up and see the transaction (US2, FR-006 to FR-009)

1. On `/billing`, enter custom amount `4` and click Add: inline error "Minimum $5".
2. Click **$25**; pay with card `4242 4242 4242 4242`, any future date, any CVC.
3. Back on `/billing?checkout=success`: within 10 s the balance reads **$30.00** and a `top_up` row
   shows amount +$25.000, balance after $30.000 (SC-002).

Replay the payment event (US2.3, SC-005):

```bash
stripe events list --limit 3                     # find the checkout.session.completed id
stripe events resend evt_XXXX
curl -s localhost:8000/v1/billing/transactions -H "authorization: Bearer $TOKEN" | jq '.items | map(.type)'
# exactly one "top_up" and one "trial_grant"
```

Abandoned checkout (US2.2): start a $100 checkout, close the Stripe page, return to `/billing`;
balance and history are unchanged.

Amount rules (US2.5, US2.6, FR-008): type 4, then 10001, then 5.555 in the custom amount: each
shows an inline reason and no checkout starts. Click the $100 chip: the field shows 100.00 and
nothing happens until "Add funds $100.00" is pressed. API: `amount_usd` "10000.01" returns 422.

## 4. Price the reference call (US3, FR-010 to FR-013)

```bash
curl -s localhost:8000/v1/pricing/quote -H 'content-type: application/json' -d '{
  "components": {"stt":{"provider":"deepgram","model":"nova-3"},
                 "llm":{"provider":"azure_openai","model":"gpt-5-mini"},
                 "tts":{"provider":"elevenlabs","model":"eleven_flash_v2_5"}, "nc": null},
  "usage": {"duration_ms":271000,"llm_input_tokens":102348,"llm_output_tokens":745,"tts_chars":2555}
}' | jq '.call | {total_usd, lines: [.lines[] | {component, billed_minutes, cost_usd, surcharge_usd, bundle_multiplier}]}'
```

Expected (SC-004):

| component | billed_minutes | cost_usd | surcharge_usd | multiplier |
|---|---|---|---|---|
| stt | 4.516667 | 0.039000 | 0.000000 | 1.0000 |
| llm | 5.117400 | 0.008000 | 0.000901 | 1.1330 |
| tts | 4.516667 | 0.204000 | 0.000000 | 1.0000 |
| platform | 4.516667 | 0.226000 | 0.000000 | 1.0000 |

`total_usd = "0.477000"`.

Rounding (US3.2): repeat with `"duration_ms": 4200` and no usage meters; `billed_seconds` is 5.

Catalog version pinning (US3.3): as an admin user, publish catalog version 2 with the STT rate
doubled (`POST /v1/admin/pricing/versions`, `effective_from` one minute ahead). After it takes
effect, a quote with `"at"` set before the change still returns `catalog_version: 1` and the old
STT rate; an existing call charge row keeps `catalog_version: 1`.

Unpriced component (edge case): quote with `"tts":{"provider":"not_a_vendor"}`; the TTS line has
`status: "unpriced"` and `complete: false`.

Public calculator (US3.4): open `http://localhost:5173/pricing` signed out, change STT, model, voice
and the minutes slider; cost per minute and the monthly estimate update on each change.

## 5. Call charge in the ledger (US2.4)

Until 003 exists, use the integration test that calls `billing.service.charge_call` with the
reference usage:

```bash
uv run --directory services/api pytest tests/integration/billing/test_charge_call.py -q
```

It asserts one `call_charge` row of `-0.477000` linked to the call id, the stored breakdown,
idempotency on a second invocation, and `call_costs.catalog_version = 1`.

## 6. Usage report (US4, FR-014)

```bash
uv run --directory services/api python -m app.usage.seed_demo --workspace ws_XXXX   # dev-only seeder: 1 call + 1 eval in window, 1 outside
curl -s "localhost:8000/v1/usage?from=2026-09-17&to=2026-10-16" -H "authorization: Bearer $TOKEN" | jq
```

Only in-window rows appear and the totals equal the sum of rows. With no usage, `/billing` shows
"No usage charges yet in this window" with the window dates.

Pick a custom range in the usage panel (US4.2): rows and totals refresh; an end date before the
start is refused inline.

## 7. Isolation and reconciliation

```bash
uv run --directory services/api pytest tests/integration/test_rls_isolation.py -q   # workspace B cannot read A's rows by id
uv run --directory services/api python -m app.billing.jobs reconcile --now          # SC-003: prints 0 mismatches
```
