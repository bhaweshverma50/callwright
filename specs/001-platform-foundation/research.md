# Research: Platform Foundation

**Feature**: 001-platform-foundation | **Date**: 2026-10-16
**Inputs**: spec.md, constitution v1.0.0, research/architecture.md, research/calldash-functional-spec.md
(sections 0, 7.4, 10.4, 10.5, 10.6, 10.7), research/pages/12-_billing.txt, research/pages/pub_pricing.txt,
research/observed-api-shapes.json.

Each entry: Decision, Rationale, Alternatives considered.

---

## R1. Line-cost rounding (resolves the $0.477 reference figure)

**Finding**: Computing the reference call at full precision gives $0.4752, not $0.477:

| Line | rate | billed minutes | exact cost | ceiling to $0.001 |
|---|---|---|---|---|
| STT | 0.0085 | 4.516667 | 0.0383917 | 0.039 |
| LLM | 0.0015 | 5.117400 | 0.0076761 | 0.008 |
| TTS | 0.0450 | 4.516667 | 0.2032500 | 0.204 |
| Platform | 0.0500 | 4.516667 | 0.2258333 | 0.226 |
| Total | | | 0.4751511 | **0.477** |

The competitor's published table (0.039, 0.008, 0.204, 0.226) only matches if every line is rounded
**up** to the next tenth of a cent and the total is the sum of the rounded lines. Half-up rounding
gives 0.038 for STT and a 0.476 total, so it is ruled out.

**Decision**: Each component cost = `ceil_to_0.001(rate_per_min × billed_minutes)`. Call total = sum
of the rounded component costs. Billed minutes, surcharge and bundle multiplier are computed at full
`Decimal` precision and stored at 6 decimals; surcharge is informational (it is already inside the
line cost) and displayed at 4 decimals, the multiplier at 2 decimals (`1.13×`).

**Rationale**: Matches the spec's SC-004 tolerance (±$0.001) and the reference worked example
exactly, and never under-bills a line. Rounding per line keeps each displayed line equal to what
was charged, so a breakdown always sums to the ledger amount.

**Alternatives considered**: Round only the total (gives $0.476, fails SC-004). Half-up per line
(gives $0.476). Bill at full precision (fractional cents in the ledger, totals that never match the
popover).

## R2. Money representation

**Decision**: `numeric(18,6)` USD in Postgres, `decimal.Decimal` in Python (context precision 28),
and decimal **strings** in JSON (`"30.000000"`, pattern `^-?\d+\.\d{1,6}$`), fields suffixed `_usd`.
The web app formats balances to 2 decimals in the header chip and 3 decimals in the transaction
table and cost popover.

**Rationale**: Floats lose cents across thousands of ledger rows; strings survive JSON round-trips
without precision loss. Six decimals leave room for sub-cent feature charges (an evaluator run can
cost $0.0004).

**Alternatives considered**: Integer micro-dollars (clean math but every reader needs a conversion
rule, and OpenAPI clients show raw integers); JSON numbers (precision loss in JavaScript).

## R3. Pricing catalog versioning and lookup

**Decision**: A catalog **version** is an integer (`1, 2, 3...`) with `effective_from`. Each version
holds a full set of rate rows `(component, provider, model | null, rate_per_min_usd, bundles[])`.
Publishing a new version copies nothing implicitly: the admin publishes a complete row set. Lookup
for an instant `t`: pick the version with the greatest `effective_from <= t`, then match
`(component, provider, model)` exactly, then fall back to `(component, provider, null)`. No match
returns `status: unpriced` for that line.

**Rationale**: Integer versions need no new ID prefix (architecture section 4 lists none for pricing)
and read naturally in a breakdown ("catalog v3"). Full row sets make each version self-describing,
so a priced call can be re-derived from `(catalog_version, usage)` alone (Principle III). The
provider-level fallback follows the competitor's documented lookup and lets one row price every
model of a flat-priced vendor, so adding a vendor stays "one catalog row" (Principle I).

**Alternatives considered**: Per-row effective dates without versions (hard to answer "which
prices applied to this call" as one value); copy-on-write deltas (smaller but every read must
replay history).

## R4. Bundle rule

**Decision**: Bundles are rows `{unit, per_min}` on surchargeable entries. Default units and sizes
(seeded in catalog v1): `llm_input_tokens` 20,000, `llm_output_tokens` 200, `tts_chars` 750.
`billed_minutes = max(duration_min, max over meters(usage / per_min))`. STT, NC and platform entries
carry no bundles, so they never surcharge. `bundle_multiplier = billed_minutes / duration_min`
(1.00 when no surcharge). For a zero-duration call, billed minutes are 0 and no charge is written.

**Rationale**: Straight from spec User Story 3 and the competitor's published rule; keeping bundles
as catalog data means a future vendor with a different unit needs no schema change.

## R5. Authentication: managed IdP behind thin API endpoints

**Decision**: Supabase Auth is the identity provider (constitution). The SPA does **not** call it
directly; it calls `/v1/auth/*` on our API, which calls Supabase Auth (GoTrue) server-side through
`services/api/app/auth/idp.py`. The API verifies access tokens (JWT) locally against the IdP JWKS
(cached 10 minutes) on every request.

**Rationale**:
- FR-003 needs per-account throttling ("5 wrong passwords within 15 minutes"), which the IdP's
  per-IP rate limits do not express. Counting failures in Redis inside our sign-in endpoint is a
  few lines.
- Workspace bootstrap (FR-002) and the trial grant happen in the same code path as verification,
  with no database triggers on the IdP schema.
- One `idp.py` adapter keeps the IdP swappable, the same idea as Principle I for vendors.

**Alternatives considered**: SPA talks to Supabase directly and a database trigger creates the
workspace (throttling not expressible, trigger logic outside migrations review); Supabase
password-verification hook (plan-dependent availability, logic split across two systems).

## R6. Login throttling

**Decision**: Redis counter `auth:fail:{sha256(lower(email))}` with a 15-minute window; on the 5th
failure further attempts return `429` with `retry_after_s` until the window expires. A second
counter per client IP (20 failures / 15 minutes) blocks credential stuffing across accounts.
A successful sign-in clears the per-account counter.

**Rationale**: Matches acceptance scenario US1.2 and lets the message state when to retry.

## R7. Workspace bootstrap timing

**Decision**: Register creates only the IdP user. The `users` row, `workspaces` row and the
`trial_grant` transaction are created on **email verification** (`POST /v1/auth/verify-email`),
in one database transaction, idempotent on the IdP subject (`users.idp_subject` unique) and on the
trial grant (`credit_transactions` partial unique index on `(workspace_id) where type='trial_grant'`).
Sign-in with an unverified email returns `403` with problem type `email-unverified` and a resend
action.

**Rationale**: Trial credit is not handed to unverified sign-ups, and FR-001 ("verification before
any call") is satisfied trivially because no workspace exists until verification.

**Alternatives considered**: Create the workspace at registration and gate calls on the flag
(gives credit to throwaway emails; more states to test).

## R8. Sign-out everywhere

**Decision**: `POST /v1/auth/sign-out` revokes the IdP session (global scope, kills refresh tokens)
and writes the token's `session_id` to Redis key `auth:revoked:{session_id}` with TTL equal to the
access token's remaining lifetime. The auth dependency rejects revoked sessions (one Redis `EXISTS`
per request, sub-millisecond). The SPA broadcasts `signed_out` on a `BroadcastChannel` so other tabs
drop their cache and redirect to `/login?next=<path>` immediately.

**Rationale**: Access tokens are stateless and would otherwise stay valid up to their expiry,
which fails acceptance scenario US1.3.

## R9. Tenant isolation

**Decision**: Every tenant table has `workspace_id` and an RLS policy
`workspace_id = current_setting('app.workspace_id')`. `core/db.py` opens one transaction per request
and runs `SET LOCAL app.workspace_id = :ws` (and `app.user_id`) before any query. The application
connects as role `callwright_app` (no `BYPASSRLS`, no `UPDATE`/`DELETE` grant on
`credit_transactions`). Migrations run as the owner role. Global tables (`pricing_catalog_versions`,
`pricing_rates`) are read-only for the app role; admin writes go through a separate
`callwright_admin` connection used only by `/v1/admin/*`.

**Rationale**: Principle V requires enforcement at the database layer, and `SET LOCAL` scopes the
setting to the transaction so pooled connections cannot leak a workspace id.

## R10. Ledger write path

**Decision**: All credit movements go through `billing.service.post_transaction()`:
1. `SELECT pg_advisory_xact_lock(hashtextextended(workspace_id, 0))`.
2. Read the latest `(seq, balance_after)` for the workspace.
3. Insert the row with `seq + 1` and `balance_after = previous + amount`.

Idempotency comes from unique keys: `external_ref` (Stripe payment intent or dispute id),
`(call_id) where type='call_charge'`, `(workspace_id, idempotency_key)` for feature charges.
A conflicting insert returns the existing row. A trigger raises on `UPDATE` or `DELETE`.
The balance is the latest `balance_after`, which by construction equals `sum(amount)`; the nightly
`reconcile_balances` job checks both (SC-003).

**Rationale**: Principle III (append-only, derived balance). The advisory lock serialises writes
per workspace without locking the whole table.

**Alternatives considered**: A mutable `balance` column (forbidden by FR-007); computing
`sum(amount)` on every read (fine at small scale but `balance_after` is needed for the history
column anyway).

## R11. Top-ups with Stripe Checkout

**Decision**: `POST /v1/billing/checkout-sessions {amount_usd}` validates `>= 5.00` and `<= 10,000.00`,
creates a Stripe Checkout Session (mode `payment`, one line item, `metadata.workspace_id`,
`client_reference_id = checkout_session row id`, Stripe idempotency key from our `Idempotency-Key`
header), stores a `checkout_sessions` row (`pending`) and returns `checkout_url`. The SPA does a
full redirect. Credit is posted only by the webhook `checkout.session.completed` with
`payment_status = paid` (and `checkout.session.async_payment_succeeded`), keyed by the payment
intent id as `external_ref`. `charge.refunded` and `charge.dispute.created` post a negative
`adjustment`. Return URLs: `/billing?checkout=success` and `/billing?checkout=canceled`.

**Rationale**: Hosted checkout keeps card data off our systems; webhook-only crediting plus a unique
`external_ref` gives exactly-once credit across replays (US2.3, SC-005).

**Alternatives considered**: Crediting on the success redirect (spoofable, double-credit risk);
Stripe Elements (more PCI surface, no benefit).

## R12. Showing the new balance quickly

**Decision**: After returning with `?checkout=success` the billing page polls `GET /v1/billing/balance`
and the first transactions page every 2 seconds for up to 30 seconds, stopping when a `top_up`
newer than the redirect appears. The header balance chip uses the same query key, so it updates
too. On window focus, the balance refetches.

**Rationale**: Stripe usually delivers the webhook within a few seconds, so polling meets SC-002
(10 seconds) with no SSE or WebSocket infrastructure (Principle VI).

## R13. Call admission inputs (balance, concurrency, grace)

**Decision**: 001 owns the rules and the inputs; 003 owns the enforcement point. 001 provides:
- `billing.service.get_balance(ws) -> Decimal` (latest `balance_after_usd`);
- `billing.service.credit_check(ws) -> CreditCheck{allowed, reason}`, refusing with
  `email_unverified` or `insufficient_credit` (balance `<= 0`);
- `workspaces.concurrency_limit` (default 5) and `settings.credit_grace_usd` (default $0.50,
  env `CREDIT_GRACE_USD`);
- `pricing.engine.price()` for the running cost estimate.

003's `calls.service.admit()` takes a per-workspace advisory lock, counts calls in `queued`,
`ringing` or `in_progress`, compares with `concurrency_limit`, calls `credit_check`, and inserts
the call in the same transaction. Mid-call, 003 recomputes the running cost on each worker event
and ends the call with `insufficient_credit` once `balance - running_cost < -grace`. Refusal and
disconnect reasons match architecture section 5.

**Rationale**: One admission path inside the transaction that creates the call row; counting rows
keeps a single source of truth with no counter to drift. 001 stays free of any dependency on the
`calls` table.

**Alternatives considered**: Redis lease set per workspace inside 001 (an extra counter that needs
crash recovery and duplicates state the calls table already has); a credit-status endpoint polled
by the worker (a second channel when worker events already reach the API every 10 seconds).

## R14. Usage events and the usage report

**Decision**: Every charge writes one `usage_events` row (`feature_key`, `quantity`, `unit`,
`raw_cost_usd`, `billable_cost_usd`, `ref_type`, `ref_id`, `txn_id`). Feature keys are dotted;
the report groups by family: `calls`, `evaluations` (`eval.*`), `simulations` (`simulator.*`),
`analytics_chat`, `prompt_generation`, `post_call_analysis`. For calls, raw cost = sum of
unrounded component costs excluding the platform fee; billable = the charged total. Other features
report the vendor list price as raw and the charged amount as billable. Window: `from`/`to`
dates in UTC, default last 30 days, inclusive of `from`, exclusive of `to + 1 day`.

**Rationale**: One table answers FR-014 with a single `GROUP BY`; `billing.charge_feature()`
(architecture section 7) is the only writer.

## R15. Public price quotes

**Decision**: One pure function `pricing.engine.price(components, usage | None, catalog)` serves
three callers: the public calculator and agent builder (`POST /v1/pricing/quote` without usage,
per-minute lines), the call charge job (with usage), and the quickstart verification (with the
reference usage). The quote endpoint is public, rate-limited to 60 requests per minute per IP in
Redis, and responses for the catalog are cacheable for 5 minutes. The calculator's monthly figure
is `per_minute_total × minutes`, computed in the browser for display only.

**Rationale**: Principle VII: one implementation of money math, tested once, used everywhere.

## R16. Contract testing and client generation

**Decision**: OpenAPI 3.1 fragments live in `specs/*/contracts/*.yaml`; `scripts/assemble_contracts.py`
merges them into `contracts/openapi.yaml` (fails on duplicate paths or schema name clashes). Contract
tests (`services/api/tests/contract/`) call the ASGI app with `httpx.AsyncClient` and validate every
response against the assembled document with `openapi-core`. A drift test compares the set of
`(method, path, status)` triples in FastAPI's generated schema with the contract. The web client
types are generated with `openapi-typescript` into `apps/web/src/api/schema.d.ts`; CI regenerates
and fails on diff.

**Rationale**: Principle VII ("contract tests fail on drift") in both directions.

**Alternatives considered**: Schemathesis property tests (useful later as fuzzing, slower in CI);
code-first OpenAPI (contradicts "contracts are the source of truth").

## R17. Public marketing pages

**Decision**: Home, pricing, enterprise, privacy and terms are routes in the same SPA under
`apps/web/src/routes/public/`, with content in TSX/Markdown files in the repo. The enterprise page
offers a contact link configured by `VITE_SALES_CONTACT_URL`. The pricing page reads
`GET /v1/pricing/catalog` and calls `POST /v1/pricing/quote`.

**Rationale**: Spec assumption "no CMS"; one deployable for the web app (Principle VI). SEO
prerendering can come later if marketing needs it.

## R18. Password and email policy

**Decision**: Passwords: minimum 10 characters, checked against the IdP's leaked-password list when
available; the register form shows a strength meter. Verification and reset emails are sent by the
IdP's SMTP integration with our templates; reset links expire after 60 minutes and are single use.
Password reset requests always return `202` to avoid revealing whether an email is registered.

## R19. IDs

**Decision**: `core/ids.py` generates prefixed ULIDs (`ws_`, `usr_`, `txn_`) with `python-ulid`.
Tables without a prefix in architecture section 4 (`checkout_sessions`, `usage_events`,
`pricing_rates`) use internal `bigint` identity keys that are never exposed as resource IDs.

**Rationale**: Avoids inventing prefixes the shared conventions do not list.

## R20. Local development stack

**Decision**: `docker-compose.yml` at the repo root runs Postgres 16 with pgvector, Redis 7 and
MinIO. Supabase Auth runs via `supabase start` (local stack) or a hosted dev project; Stripe test
mode with `stripe listen --forward-to localhost:8000/v1/webhooks/stripe`.

**Rationale**: Managed services in production, the same APIs locally (Principle VI).
