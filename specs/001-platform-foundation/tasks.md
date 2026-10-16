---
description: "Task list for 001-platform-foundation"
---

# Tasks: Platform Foundation

**Input**: Design documents from `specs/001-platform-foundation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required. Constitution Principle VII makes contract tests and money tests mandatory and
test-first. Every test task below precedes the implementation it covers and must fail first.

**Organization**: Grouped by user story (US1 to US4 from spec.md). Paths follow
research/architecture.md section 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US4; Setup, Foundational and Polish tasks carry no story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository skeleton every feature builds on.

- [ ] T001 Create the top-level layout from plan.md: `apps/web/`, `services/api/app/`, `services/api/tests/{unit,contract,integration}/`, `contracts/`, `scripts/`
- [ ] T002 Initialise the API project in `services/api/pyproject.toml` (Python 3.12; fastapi, pydantic v2, sqlalchemy[asyncio], asyncpg, alembic, arq, redis, python-ulid, pyjwt[crypto], httpx, stripe; dev: pytest, pytest-asyncio, openapi-core, ruff, mypy)
- [ ] T003 [P] Initialise the web app in `apps/web/package.json` with Vite + React 18 + TypeScript, TanStack Query, React Router, Tailwind, Radix, openapi-fetch, openapi-typescript, Vitest, Testing Library, Playwright; config in `apps/web/vite.config.ts`, `apps/web/tailwind.config.ts`
- [ ] T004 [P] Add `docker-compose.yml` at the repo root with Postgres 16 + pgvector, Redis 7 and MinIO, plus `services/api/.env.example`
- [ ] T005 [P] Configure ruff and mypy in `services/api/pyproject.toml` and ESLint + Prettier in `apps/web/.eslintrc.cjs`
- [ ] T006 [P] Write `scripts/assemble_contracts.py`: merge `specs/*/contracts/*.yaml` into `contracts/openapi.yaml`, rewrite cross-file `$ref`s to local refs, merge identical duplicate components, fail on conflicting duplicates or duplicate paths; `--check` mode exits non-zero when the committed file is stale
- [ ] T007 [P] Add CI in `.github/workflows/ci.yml`: compose services, ruff, mypy, pytest unit/contract/integration, `assemble_contracts.py --check`, openapi-typescript regeneration diff, web lint, Vitest, Playwright

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core plumbing every user story needs: config, RLS sessions, auth dependency, errors,
IDs, the ledger table and writer, contract test harness, app shell skeleton.

**CRITICAL**: No user story work starts before this phase is complete.

- [ ] T008 Implement settings in `services/api/app/core/config.py` (DB URLs for app and admin roles, Redis URL, IdP URL and keys, Stripe keys, `trial_credit_usd` 5.00, `default_concurrency` 5, `credit_grace_usd` 0.50, web base URL)
- [ ] T009 [P] Implement prefixed ULID helpers in `services/api/app/core/ids.py` (`new_id("ws")`, validators per prefix)
- [ ] T010 [P] Implement RFC 9457 problem responses in `services/api/app/core/errors.py`: problem types, `code`, `retry_after_s`, Pydantic validation errors mapped to `errors[{pointer, code, message}]`
- [ ] T011 Implement `services/api/app/core/db.py`: async engines for `callwright_app` and `callwright_admin`, one transaction per request, `SET LOCAL app.workspace_id` and `app.user_id`
- [ ] T012 Implement `services/api/app/core/auth.py`: JWKS fetch with 10-minute cache, JWT verify, `auth:revoked:{session_id}` check, dependencies `current_user`, `current_workspace` (sets RLS), `require_admin`, `require_service`
- [ ] T013 [P] Implement the Redis fixed-window limiter in `services/api/app/core/rate_limit.py`
- [ ] T014 [P] Implement arq settings and cron registration in `services/api/app/core/jobs.py`
- [ ] T015 Create Alembic env in `services/api/app/migrations/env.py` and migration `services/api/app/migrations/versions/0001_foundation.py`: roles `callwright_app` and `callwright_admin`, tables `users`, `workspaces`, `credit_transactions` (sign CHECKs, partial unique indexes, immutability trigger, `SELECT, INSERT` grant only), `usage_events`, RLS policies per data-model.md
- [ ] T016 [P] Create SQLAlchemy models in `services/api/app/workspaces/models.py` (User, Workspace)
- [ ] T017 [P] Create SQLAlchemy models in `services/api/app/billing/models.py` (CreditTransaction) and `services/api/app/usage/models.py` (UsageEvent)
- [ ] T018 Write failing ledger tests in `services/api/tests/unit/billing/test_ledger.py`: balance_after chain, sign rules per type, idempotency by `external_ref`, `idempotency_key` and call id, concurrent posts for one workspace serialise without gaps in `seq`
- [ ] T019 Write failing test in `services/api/tests/integration/billing/test_ledger_immutable.py`: `UPDATE` and `DELETE` on `credit_transactions` raise for the app role
- [ ] T020 Implement `post_transaction()` and `get_balance()` in `services/api/app/billing/service.py` (advisory xact lock, seq, balance_after, conflict returns existing row) until T018 and T019 pass
- [ ] T021 Create the FastAPI app in `services/api/app/main.py` with `/v1` prefix, problem handlers, router registration, and `GET /v1/health` per `contracts/core.yaml`
- [ ] T022 [P] Build the contract test harness in `services/api/tests/contract/conftest.py`: load assembled `contracts/openapi.yaml`, validate every response with openapi-core, fixtures for a verified user, workspace and token
- [ ] T023 [P] Write the drift test in `services/api/tests/contract/test_drift.py` comparing `(method, path, status)` triples between `app.openapi()` and the contract
- [ ] T024 [P] Write the RLS isolation test harness in `services/api/tests/integration/test_rls_isolation.py` (two workspaces; every tenant table is unreadable across workspaces by id); extended by later stories
- [ ] T025 Run `scripts/assemble_contracts.py` and generate `apps/web/src/api/schema.d.ts`; add the typed client with auth header and refresh-on-401 in `apps/web/src/api/client.ts`
- [ ] T026 [P] Create the query client and router skeleton in `apps/web/src/app/queryClient.ts` and `apps/web/src/app/router.tsx` (public and protected route groups)
- [ ] T027 [P] Create design-system primitives in `apps/web/src/components/` (`Button.tsx`, `Input.tsx`, `Dialog.tsx`, `Table.tsx`, `Toast.tsx`, `Money.tsx`, `EmptyState.tsx`) with Tailwind tokens and light/dark themes

**Checkpoint**: API boots, health passes contract test, ledger writer passes money tests, web app renders an empty router.

---

## Phase 3: User Story 1 - Sign up and land in a workspace (Priority: P1) MVP

**Goal**: Register, verify, sign in, land on the dashboard inside the shell with balance and navigation; throttled sign-in; global sign-out; password reset; public marketing pages.

**Independent Test**: Register a fresh email, verify, sign in; workspace shows $5.00, the email, and working navigation to every area (quickstart section 2).

### Tests for User Story 1 (write first, must fail)

- [ ] T028 [P] [US1] Contract tests for all `contracts/auth.yaml` operations in `services/api/tests/contract/test_auth_contract.py`
- [ ] T029 [P] [US1] Contract tests for `contracts/workspaces.yaml` in `services/api/tests/contract/test_workspaces_contract.py`
- [ ] T030 [P] [US1] Integration test: verify-email bootstraps user, workspace (concurrency 5) and one `trial_grant` of 5.00; second verification is a no-op, in `services/api/tests/integration/auth/test_bootstrap.py`
- [ ] T031 [P] [US1] Integration test: 5 failures then 429 with `retry_after_s`; success clears the counter; per-IP limit, in `services/api/tests/integration/auth/test_throttle.py`
- [ ] T032 [P] [US1] Integration test: sign-out revokes the session; the old access token gets 401, in `services/api/tests/integration/auth/test_sign_out.py`
- [ ] T033 [P] [US1] Integration test: unverified sign-in returns 403 `email_unverified`; reset request returns 202 for unknown emails, in `services/api/tests/integration/auth/test_verification_and_reset.py`
- [ ] T034 [P] [US1] Playwright journey register, verify via mail catcher, land on dashboard, see $5.00 and 11 nav items, in `apps/web/tests/e2e/signup.spec.ts`

### Implementation for User Story 1

- [ ] T035 [US1] Implement the IdP wrapper in `services/api/app/auth/idp.py` (sign-up, password grant, refresh, verify OTP token hash, recover, update password, global sign-out)
- [ ] T036 [US1] Implement `services/api/app/auth/schemas.py` and `services/api/app/auth/service.py` (register, verify plus bootstrap call, sign-in with throttle counters, refresh, sign-out with revocation key, reset request and confirm)
- [ ] T037 [US1] Implement `bootstrap_workspace(idp_user)` in `services/api/app/workspaces/service.py` (user, workspace, `trial_grant` via `billing.service.post_transaction`, one transaction, idempotent)
- [ ] T038 [US1] Implement routes in `services/api/app/auth/router.py` and `services/api/app/workspaces/router.py` (`GET /v1/me`, `PATCH /v1/workspaces/current`) with schemas in `services/api/app/workspaces/schemas.py`
- [ ] T039 [P] [US1] Build `apps/web/src/app/session.ts` (token storage, refresh) and `apps/web/src/app/authChannel.ts` (BroadcastChannel sign-out across tabs)
- [ ] T040 [P] [US1] Build `apps/web/src/app/AuthGuard.tsx` (redirect to `/login?next=`, return after sign-in, silent refresh, sign-in on refresh failure)
- [ ] T041 [P] [US1] Build `apps/web/src/routes/public/Login.tsx`, `Register.tsx` (strength meter, 10-char minimum), `VerifyEmail.tsx`, `ForgotPassword.tsx`, `ResetPassword.tsx`, including throttle and expired-link messages
- [ ] T042 [US1] Build the shell in `apps/web/src/app/Shell.tsx`, `NavRail.tsx` (collapsible icon rail, 11 areas), `BalanceChip.tsx` (from `/v1/me`, then `/v1/billing/balance` once US2 lands), `UserMenu.tsx` (email, avatar initials, sign-out)
- [ ] T043 [P] [US1] Build `apps/web/src/routes/dashboard/DashboardPlaceholder.tsx` (empty state, replaced by 006) and `apps/web/src/routes/placeholders/AreaPlaceholder.tsx` for areas whose spec has not shipped
- [ ] T044 [P] [US1] Build public pages `apps/web/src/routes/public/Home.tsx`, `Enterprise.tsx` (contact link from `VITE_SALES_CONTACT_URL`), `Privacy.tsx`, `Terms.tsx` with Callwright copy (FR-016)
- [ ] T045 [US1] Extend `services/api/tests/integration/test_rls_isolation.py` for `users` and `workspaces`

**Checkpoint**: US1 independently demoable (quickstart section 2).

---

## Phase 4: User Story 2 - Top up credit and see every transaction (Priority: P1)

**Goal**: Live balance, hosted checkout top-ups (presets and custom, minimum $5), exactly-once crediting, paginated history, refunds and disputes as negative adjustments, credit check for call admission.

**Independent Test**: Test-mode payment updates balance and history without reload; $4 is rejected; replayed webhook credits once (quickstart section 3).

### Tests for User Story 2 (write first, must fail)

- [ ] T046 [P] [US2] Contract tests for `contracts/billing.yaml` in `services/api/tests/contract/test_billing_contract.py`
- [ ] T047 [P] [US2] Unit tests for amount validation (min 5.00, max 10,000.00, 2-decimal input) in `services/api/tests/unit/billing/test_checkout_amounts.py`
- [ ] T048 [P] [US2] Integration test with signed Stripe fixtures: `checkout.session.completed` posts one `top_up`; replay and `async_payment_succeeded` for the same intent post nothing; invalid signature 400; unknown event 200, in `services/api/tests/integration/billing/test_stripe_webhook.py`
- [ ] T049 [P] [US2] Integration test: expired or abandoned session writes no transaction; `charge.refunded` and `charge.dispute.created` write negative `adjustment` rows, in `services/api/tests/integration/billing/test_checkout_lifecycle.py`
- [ ] T050 [P] [US2] Unit tests for `credit_check` (balance 0 refused `insufficient_credit`, unverified refused `email_unverified`, positive allowed) in `services/api/tests/unit/billing/test_credit_check.py`
- [ ] T051 [P] [US2] Playwright journey: $4 rejected, $25 top-up with test card, balance $30.00 and new row within 10 s, in `apps/web/tests/e2e/topup.spec.ts`

### Implementation for User Story 2

- [ ] T052 [US2] Add migration `services/api/app/migrations/versions/0002_checkout_sessions.py` and the `CheckoutSession` model in `services/api/app/billing/models.py`
- [ ] T053 [US2] Implement `services/api/app/billing/stripe_gateway.py` (create session with metadata, idempotency key, return URLs; verify webhook signature)
- [ ] T054 [US2] Implement in `services/api/app/billing/service.py`: `create_checkout()`, `handle_stripe_event()`, `list_transactions()`, `get_transaction()`, `credit_check()`
- [ ] T055 [US2] Implement `services/api/app/billing/schemas.py` and routes in `services/api/app/billing/router.py` (balance, checkout-sessions with `Idempotency-Key`, transactions list and detail, `POST /v1/webhooks/stripe`)
- [ ] T056 [US2] Implement the nightly `reconcile_balances` job and its CLI entry (`python -m app.billing.jobs reconcile --now`) in `services/api/app/billing/jobs.py` (SC-003)
- [ ] T057 [P] [US2] Build `apps/web/src/routes/billing/BillingPage.tsx` with `TopUpCard.tsx` (presets 25/100/500/1000, custom with minimum $5) and the post-checkout polling (2 s for up to 30 s)
- [ ] T058 [P] [US2] Build `apps/web/src/routes/billing/TransactionsTable.tsx` (date, type, amount, balance after, call id, description; 20 per page; newest first)
- [ ] T059 [US2] Switch `apps/web/src/app/BalanceChip.tsx` to the shared balance query with refetch on focus
- [ ] T060 [US2] Extend `services/api/tests/integration/test_rls_isolation.py` for `credit_transactions` and `checkout_sessions`

**Checkpoint**: US1 and US2 both work independently. US2.4 (call charge) is verified in US3.

---

## Phase 5: User Story 3 - Know the price of a call before and after it happens (Priority: P2)

**Goal**: Versioned catalog, the pricing engine with whole-second round-up, bundle rule and per-line ceiling, quotes for agents and the public calculator, call charges with stored breakdowns.

**Independent Test**: Reference call prices to $0.477 with LLM surcharge about $0.0009 and multiplier 1.13; 4.2 s bills 5 s (quickstart section 4).

### Tests for User Story 3 (write first, must fail)

- [ ] T061 [P] [US3] Money tests in `services/api/tests/unit/pricing/test_engine.py`: reference call total 0.477 and lines 0.039/0.008/0.204/0.226; LLM billed minutes 5.117400, surcharge 0.000901, multiplier 1.1330; TTS no surcharge; 4.2 s bills 5 s; zero duration bills 0; NC line when selected; STT/NC/platform never surcharge
- [ ] T062 [P] [US3] Unit tests for catalog lookup in `services/api/tests/unit/pricing/test_catalog_lookup.py`: exact model match, provider fallback, unpriced line, version chosen by `at`, publish rejects past or non-increasing `effective_from`, bundles only on llm/tts
- [ ] T063 [P] [US3] Contract tests for `contracts/pricing.yaml` in `services/api/tests/contract/test_pricing_contract.py` (catalog, quote with and without usage, admin list and publish with 403 for non-admins)
- [ ] T064 [P] [US3] Integration test for `charge_call` in `services/api/tests/integration/billing/test_charge_call.py`: one `call_charge` of -0.477000 linked to the call, `call_costs` row with catalog version, one `usage_events` row, second call is a no-op, older call keeps its version after a rate change
- [ ] T065 [P] [US3] Vitest for the calculator in `apps/web/src/routes/public/PricingCalculator.test.tsx` (per-minute total from quote, monthly = per-minute x minutes, slider 0 to 250,000)

### Implementation for User Story 3

- [ ] T066 [US3] Add migration `services/api/app/migrations/versions/0003_pricing_catalog.py` (versions, rates, seed version 1 per data-model.md) and models in `services/api/app/pricing/models.py`
- [ ] T067 [US3] Implement the pure engine in `services/api/app/pricing/engine.py` (`price(components, usage, catalog) -> Quote`, Decimal math, ceiling to 0.001 per line) until T061 passes
- [ ] T068 [US3] Implement `services/api/app/pricing/service.py` (catalog by instant, lookup with fallback, `quote()`, admin publish) until T062 passes
- [ ] T069 [US3] Implement `services/api/app/pricing/schemas.py` and `services/api/app/pricing/router.py` (public catalog with `Cache-Control: public, max-age=300`, public quote rate-limited 60/min/IP, admin versions)
- [ ] T070 [US3] Add migration `services/api/app/migrations/versions/0004_call_costs.py` and the `CallCost` model in `services/api/app/billing/models.py`
- [ ] T071 [US3] Implement `charge_call(CallUsage)` in `services/api/app/billing/service.py` (catalog at call start, engine, `call_costs`, `call_charge` transaction, `usage_events` row, idempotent per call) and expose `cost_breakdown` on call-charge transactions
- [ ] T072 [P] [US3] Build `apps/web/src/routes/billing/CostBreakdownPopover.tsx` (header `m:ss · X.XXm · $Y/m avg`, base lines, surcharge block with multiplier) and attach it to call-charge rows in `TransactionsTable.tsx`
- [ ] T073 [P] [US3] Build `apps/web/src/routes/public/Pricing.tsx` and `PricingCalculator.tsx` (STT, model and voice pickers from catalog; minutes slider; five-component explainer; surcharge rule and worked example)
- [ ] T074 [US3] Extend `services/api/tests/integration/test_rls_isolation.py` for `call_costs`

**Checkpoint**: Pricing is shared by quote, calculator and call charge from one engine.

---

## Phase 6: User Story 4 - See where the money went (Priority: P3)

**Goal**: Usage per feature family for a date window with raw and billable costs; `charge_feature()` for later features.

**Independent Test**: One call and one evaluation in range and one outside; only in-range rows and correct totals (quickstart section 6).

### Tests for User Story 4 (write first, must fail)

- [ ] T075 [P] [US4] Contract tests for `contracts/usage.yaml` in `services/api/tests/contract/test_usage_contract.py`
- [ ] T076 [P] [US4] Integration test in `services/api/tests/integration/usage/test_usage_window.py`: default window 30 days, inclusive dates, out-of-range rows excluded, family grouping (`eval.*` to `evaluations`), totals equal row sums, window over 366 days rejected
- [ ] T077 [P] [US4] Money test in `services/api/tests/unit/billing/test_charge_feature.py`: one `feature_charge` plus one `usage_events` row, idempotent per key, refused with `insufficient_credit` when balance is at or below zero

### Implementation for User Story 4

- [ ] T078 [US4] Implement `charge_feature()` in `services/api/app/billing/service.py`
- [ ] T079 [US4] Implement the report query in `services/api/app/usage/service.py`, schemas in `services/api/app/usage/schemas.py`, route in `services/api/app/usage/router.py`
- [ ] T080 [P] [US4] Build `apps/web/src/routes/billing/UsagePanel.tsx` (window picker defaulting to last 30 days, rows per family with expandable details, empty state "No usage charges yet in this window" with dates)
- [ ] T081 [P] [US4] Add the dev-only seeder `services/api/app/usage/seed_demo.py` used by quickstart section 6
- [ ] T082 [US4] Extend `services/api/tests/integration/test_rls_isolation.py` for `usage_events`

**Checkpoint**: All four stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T083 [P] Add OpenTelemetry tracing to `services/api/app/main.py` (FastAPI, SQLAlchemy, httpx, Redis instrumentation; `workspace_id` attribute)
- [ ] T084 [P] Load the secrets (Stripe keys, webhook secret, IdP service key) from the encrypted `secrets` store in `services/api/app/core/config.py`; confirm no endpoint echoes them
- [ ] T085 [P] Leave guard and aggregated error dialog primitives in `apps/web/src/components/LeaveGuard.tsx` and `apps/web/src/components/ErrorSummaryDialog.tsx` (reused by 002)
- [ ] T086 Performance check: `GET /v1/me` and `GET /v1/billing/balance` p95 under 150 ms with 1M ledger rows, recorded in `services/api/tests/integration/test_perf_smoke.py`
- [ ] T087 Run every step of `specs/001-platform-foundation/quickstart.md` and fix gaps

---

## Phase 8: Cross-spec additions (architecture v1.1)

**Purpose**: Interfaces later features rely on that 001 owns. Added during cross-spec reconciliation on 2026-10-16.

- [ ] T088 [P] Encrypted secrets store in `services/api/app/core/secrets.py`: `put_secret`, `get_secret`, `mask_secret`, KMS-wrapped data key, `secrets` table migration with RLS; unit tests in `services/api/tests/unit/core/test_secrets.py` (used by 005 HTTP tool headers and 010 SIP and WhatsApp credentials)
- [ ] T089 [P] Workspace setting `recording_default` (boolean, default true) in `services/api/app/workspaces/models.py` and `schemas.py`, exposed on the workspace settings read and update endpoints (consumed by 003 call admission)
- [ ] T090 Pricing catalog additions in `services/api/app/pricing/`: component `embedding` (per 1K tokens, used by 005 ingestion) and feature keys `flow_assistant`, `voice_copilot`, `analytics_chat`, `prompt_generation`, `post_call_analysis`, `eval.<name>`, `simulator.<step>`, `issues.<step>`; money tests extended in `services/api/tests/unit/pricing/test_engine.py`

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1): none
- Foundational (Phase 2): after Setup; blocks all stories
- US1 (Phase 3): after Foundational
- US2 (Phase 4): after Foundational; the balance chip switch (T059) after T042
- US3 (Phase 5): after Foundational; `charge_call` (T071) uses the ledger writer (T020); the popover (T072) attaches to T058
- US4 (Phase 6): after Foundational; meaningful data arrives once US3 writes call usage events
- Polish (Phase 7): after the stories in scope

### Downstream features

- 002 needs: US1 (auth, shell), US3 quote endpoint, US4 `charge_feature` (prompt generation)
- 003 needs: `credit_check`, `get_balance`, `concurrency_limit`, `charge_call`, `pricing.service.quote`

### Within Each Story

Tests first and failing, then models and migrations, then services, then routes, then UI.

### Parallel Opportunities

- Setup: T003 to T007 in parallel after T001 and T002
- Foundational: T009, T010, T013, T014, T016, T017, T022 to T024, T026, T027
- US1: all tests T028 to T034 together; web tasks T039 to T041, T043, T044 together
- US2: tests T046 to T051 together; T057 and T058 together
- US3: tests T061 to T065 together; T072 and T073 together

## Parallel Example: User Story 3

```bash
Task: "Money tests in services/api/tests/unit/pricing/test_engine.py"
Task: "Catalog lookup tests in services/api/tests/unit/pricing/test_catalog_lookup.py"
Task: "Contract tests in services/api/tests/contract/test_pricing_contract.py"
Task: "charge_call integration test in services/api/tests/integration/billing/test_charge_call.py"
```

## Implementation Strategy

### MVP First

1. Phases 1 and 2.
2. Phase 3 (US1): sign-up into the shell. Validate with quickstart section 2.
3. Phase 4 (US2): credit. Calls in later features cannot run without it.

### Incremental Delivery

US3 next (002's cost card and 003's call charging depend on it), then US4. Each phase ends at a
checkpoint that can be demoed alone.

## Notes

- Money and contract tests are mandatory, not optional, under the constitution.
- Migrations are forward-only; `0001` to `0004` are reviewed with this feature.
- Keep `pricing/engine.py` free of I/O so the money tests stay fast and deterministic.
