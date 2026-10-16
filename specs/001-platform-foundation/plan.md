# Implementation Plan: Platform Foundation

**Branch**: `001-platform-foundation` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-platform-foundation/spec.md`

## Summary

Accounts, workspaces, the app shell, a prepaid credit ledger, a versioned pricing catalog with the
bundle surcharge rule, a public pricing calculator, and per-feature usage reporting. Every later
feature depends on this one: it provides authentication and the RLS-scoped database session
(`core`), the `/v1/me` identity payload, the ledger API that all charges go through
(`billing.post_transaction`, `billing.charge_feature`, `billing.charge_call`), the credit check
used by 003's call admission (`billing.credit_check`), and the single pricing engine
(`pricing.engine.price`).

Technical approach (see research.md): Supabase Auth behind thin `/v1/auth/*` endpoints for
throttling and workspace bootstrap; an append-only ledger serialised per workspace with an advisory
lock; Stripe Checkout with webhook-only crediting keyed by payment intent; integer catalog
versions with exact-then-provider fallback lookup; per-line cost rounded up to $0.001 (the only
rule that reproduces the $0.477 reference call); one `usage_events` table for the usage report.
Concurrency counting lives in 003's admission transaction; 001 supplies the limit, the credit
check and the grace amount (research R13).

## Technical Context

**Language/Version**: Python 3.12 (API), TypeScript 5.x (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic, arq,
`python-ulid`, `stripe`, `pyjwt[crypto]` (JWKS verification), `httpx` (IdP calls); web: React 18,
Vite, TanStack Query, React Router, Tailwind, Radix primitives, `openapi-typescript`,
`openapi-fetch`
**Storage**: PostgreSQL 16 (RLS on every tenant table; pgvector installed but unused here), Redis 7
(arq queue, rate limits, throttling counters, session revocations)
**Testing**: pytest + pytest-asyncio, `httpx.AsyncClient` against the ASGI app, `openapi-core` for
contract validation, Postgres and Redis from `docker-compose.yml` in CI; web: Vitest + Testing
Library, Playwright for the sign-up and top-up journeys
**Target Platform**: Linux containers for `services/api` (HTTP and arq worker from one image);
static SPA on a CDN
**Project Type**: Web application (SPA + API service), per research/architecture.md section 2
**Performance Goals**: `GET /v1/me` and `GET /v1/billing/balance` p95 under 150 ms; `credit_check`
p95 under 10 ms (one indexed read); top-up visible within 10 s of payment (SC-002); quote endpoint p95 under 100 ms
**Constraints**: Money in `numeric(18,6)` and `Decimal`, never floats; ledger rows immutable; no
endpoint returns another workspace's rows even with a forged ID (RLS)
**Scale/Scope**: v1 target 1,000 workspaces, 100 concurrent calls platform-wide, 1M ledger rows per
year; 16 public and app screens (shell, 5 auth pages, billing, 5 marketing pages, dashboard
placeholder, area placeholders)

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design (no changes).*

| Gate | Principle | Status | Evidence |
|---|---|---|---|
| Vendor behind adapter | I | PASS | Pricing is keyed by `(component, provider, model)` strings from catalog rows; adding a vendor is one row (research R3). The IdP (`auth/idp.py`) and payments (`billing/stripe_gateway.py`) are each one wrapper file. No voice vendor code in this feature. |
| Latency impact stated | II | PASS | Not on the per-turn hot path. `credit_check` runs once at call admission (one indexed read on `credit_transactions`, budget 10 ms p95). Mid-call cost checks run in 003's event handler, off the audio path. |
| Metering impact stated | III | PASS | This feature implements metering: whole-second round-up, bundle rule, per-line ceiling to $0.001 (R1), catalog version stored on every breakdown, append-only ledger with derived balance (R10), nightly reconciliation (SC-003). |
| Measurability path | IV | PASS | No evaluator logic here. Usage events give every later quality feature (evals, simulations) a cost record per run. |
| Tenancy and privacy review | V | PASS | RLS on `users`, `workspaces`, `credit_transactions`, `checkout_sessions`, `call_costs`, `usage_events`; app role lacks `BYPASSRLS` and `UPDATE/DELETE` on the ledger (R9). Stripe secret and webhook secret come from the secrets store and are never returned. Password reset never reveals account existence (R18). |
| Complexity justified | VI | PASS | One API service plus its arq worker; no new services. Polling instead of SSE for balance (R12); marketing pages inside the SPA (R17). |
| Contract and money tests listed | VII | PASS | Contract tests for all six contract files; test-first money tests: pricing engine (reference call, 4.2 s rounding, fallback lookup, unpriced line, version pinning), ledger (chain, append-only trigger, idempotent top-up and call charge), Stripe webhook replay, reconciliation. Listed in tasks.md before implementation tasks. |

## Project Structure

### Documentation (this feature)

```text
specs/001-platform-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 decisions R1 to R20
├── data-model.md        # Phase 1 entities, tables, RLS, state rules
├── quickstart.md        # Phase 1 end-to-end verification
├── contracts/           # Phase 1 OpenAPI 3.1 fragments, one per API module
│   ├── core.yaml        # health + shared components (Problem, Page, Money)
│   ├── auth.yaml
│   ├── workspaces.yaml
│   ├── billing.yaml     # balance, checkout, transactions, Stripe webhook
│   ├── pricing.yaml     # catalog, quote, admin versions
│   └── usage.yaml
├── checklists/requirements.md
└── tasks.md             # Phase 2 (speckit-tasks)
```

### Source Code (repository root)

```text
docker-compose.yml                      # Postgres 16 + pgvector, Redis 7, MinIO (local and CI)
scripts/assemble_contracts.py           # merges specs/*/contracts/*.yaml into contracts/openapi.yaml
contracts/openapi.yaml                  # generated, committed
.github/workflows/ci.yml                # lint, types, unit, contract, web tests

services/api/
├── pyproject.toml
├── app/
│   ├── main.py                         # FastAPI app, router registration, problem+json handlers
│   ├── core/
│   │   ├── config.py                   # settings (trial credit, concurrency default, grace, URLs)
│   │   ├── db.py                       # async engine, per-request transaction, SET LOCAL app.workspace_id
│   │   ├── auth.py                     # JWT verify via JWKS, revocation check, current_user/workspace deps
│   │   ├── ids.py                      # prefixed ULIDs
│   │   ├── errors.py                   # RFC 9457 problem types, validation error mapping
│   │   ├── ratelimit.py                # Redis fixed-window limiter
│   │   └── jobs.py                     # arq WorkerSettings, cron registration
│   ├── auth/        router.py schemas.py service.py idp.py
│   ├── workspaces/  router.py schemas.py models.py service.py
│   ├── billing/     router.py schemas.py models.py service.py jobs.py stripe_gateway.py
│   ├── pricing/     router.py schemas.py models.py service.py engine.py
│   ├── usage/       router.py schemas.py models.py service.py
│   └── migrations/
│       ├── env.py
│       └── versions/0001_foundation.py, 0002_pricing_catalog_seed.py
└── tests/
    ├── unit/{pricing,billing,auth}/
    ├── contract/
    └── integration/{auth,billing,pricing,usage}/

apps/web/
├── package.json, vite.config.ts, tailwind.config.ts
└── src/
    ├── app/        main.tsx router.tsx AuthGuard.tsx queryClient.ts Shell.tsx NavRail.tsx
    │               BalanceChip.tsx UserMenu.tsx authChannel.ts session.ts
    ├── routes/
    │   ├── public/   Home.tsx Pricing.tsx PricingCalculator.tsx Enterprise.tsx Privacy.tsx Terms.tsx
    │   │             Login.tsx Register.tsx VerifyEmail.tsx ForgotPassword.tsx ResetPassword.tsx
    │   ├── billing/  BillingPage.tsx TopUpCard.tsx TransactionsTable.tsx CostBreakdownPopover.tsx UsagePanel.tsx
    │   ├── settings/ SettingsPage.tsx            # FR-017
    │   ├── NotFound.tsx                          # FR-018 catch-all inside the shell
    │   ├── dashboard/ DashboardPlaceholder.tsx   # replaced by 006
    │   └── placeholders/ AreaPlaceholder.tsx     # areas whose spec has not shipped
    ├── components/ Button.tsx Dialog.tsx Table.tsx Toast.tsx Money.tsx EmptyState.tsx ...
    └── api/        schema.d.ts (generated) client.ts problems.ts (problem to message, FR-019)
```

**Structure Decision**: The web application layout from research/architecture.md section 2.
Module-internal extras beyond `router/schemas/models/service/jobs` are single-purpose wrappers
(`auth/idp.py`, `billing/stripe_gateway.py`) and the pure pricing math (`pricing/engine.py`, kept
apart so it can be unit-tested without a database). `core/rate_limit.py` and `core/jobs.py` are
shared infrastructure used by later features.

## Phase 0: Research

All unknowns resolved in [research.md](./research.md). Highlights:
- R1: per-line ceiling to $0.001 reproduces $0.477; full precision gives $0.4752 and would fail SC-004.
- R5 to R8: auth flows through our API for throttling, bootstrap and global sign-out.
- R10, R11: ledger serialisation and Stripe idempotency.
- R13: 001 supplies balance, credit check, concurrency limit and grace; 003 enforces at admission.

## Phase 1: Design

- [data-model.md](./data-model.md): `users`, `workspaces`, `credit_transactions`,
  `checkout_sessions`, `pricing_catalog_versions`, `pricing_rates`, `call_costs`, `usage_events`,
  plus Redis keys.
- [contracts/](./contracts/): 6 fragments, 21 operations.
- [quickstart.md](./quickstart.md): register, verify, top up, replay webhook, price the reference
  call, read usage.

### Interfaces exposed to later features (in-process Python, same API codebase)

| Function | Used by | Contract |
|---|---|---|
| `core.auth.current_workspace` (FastAPI dependency) | every module | resolves user and workspace, sets RLS |
| `billing.service.get_balance(ws) -> Decimal` | 003 admission and mid-call checks | derived from ledger |
| `billing.service.credit_check(ws) -> CreditCheck` | 003 `calls.service.admit()` | reasons `email_unverified`, `insufficient_credit` |
| `workspaces.concurrency_limit`, `settings.credit_grace_usd` | 003 admission and mid-call checks | defaults 5 and $0.50 |
| `billing.service.charge_call(CallUsage) -> CostBreakdown` | 003 post-call pipeline step 2 | idempotent per `call_id` |
| `pricing.service.quote(components, usage, at)` | 003 running cost and readiness, 002 cost card | wraps `engine.price` with catalog lookup |
| `billing.service.charge_feature(ws, feature_key, quantity, unit, raw_cost, billable_cost, ref, idempotency_key)` | 002 prompt AI, 006, 007, 008 | idempotent per key |
| `pricing.engine.price(components, usage, catalog) -> Quote` | 002 cost card (via `/v1/pricing/quote`) | pure function |

`CallUsage` = `{workspace_id, call_id, agent_version_id, started_at, duration_ms, components:
{stt, llm, tts, nc}, meters: {llm_input_tokens, llm_output_tokens, tts_chars}}`. 003 builds it from
the call's AgentConfig snapshot and summed CallEvent meters. Pricing uses the catalog version in
effect at `started_at` (US3.3).

## Complexity Tracking

No constitution violations. Additions worth recording:

| Addition | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Auth endpoints wrap the IdP instead of SPA-direct | FR-003 per-account throttling and FR-002 bootstrap in one reviewed code path | SPA-direct needs IdP hooks or DB triggers outside our migrations |
| `docker-compose.yml`, `scripts/assemble_contracts.py` at repo root | Local/CI stack and the contract assembly step implied by architecture section 2 | Not listed in architecture's tree; no alternative location defined |
