# Data Model: Platform Foundation

**Feature**: 001-platform-foundation | **Date**: 2026-10-16

Conventions: Postgres 16, `timestamptz` in UTC, money `numeric(18,6)` USD, prefixed ULID text keys
where architecture section 4 defines a prefix, otherwise `bigint generated always as identity`.
"RLS" means `ENABLE ROW LEVEL SECURITY` plus `FORCE ROW LEVEL SECURITY` with policy
`workspace_id = current_setting('app.workspace_id', true)`.

---

## users

A person who signs in. Not tenant-scoped by `workspace_id`; RLS policy
`id = current_setting('app.user_id', true)`.

| Column | Type | Rules |
|---|---|---|
| id | text PK | `usr_` ULID |
| idp_subject | text, unique, not null | IdP user id (`sub` claim) |
| email | citext, unique, not null | lowercased, RFC 5322 shape |
| email_verified_at | timestamptz null | set on verification |
| is_admin | boolean, default false | platform staff flag; grants `/v1/admin/*` |
| created_at | timestamptz, default now() | |

## workspaces

The tenant boundary. One per user in v1 (`owner_user_id` unique).

| Column | Type | Rules |
|---|---|---|
| id | text PK | `ws_` ULID |
| name | text, not null | 1 to 80 chars; default "<email local part>'s workspace" |
| owner_user_id | text FK users.id, unique | |
| concurrency_limit | int, not null | default `DEFAULT_CONCURRENCY` (5), range 1 to 500 |
| recording_default | boolean, not null, default true | workspace call recording default (T089, FR-017); read by 003 admission |
| created_at | timestamptz | |

RLS: policy on `id = current_setting('app.workspace_id', true)`.

## credit_transactions (Credit Transaction)

Append-only ledger. RLS. App role has `SELECT, INSERT` only; trigger `credit_transactions_immutable`
raises on `UPDATE` and `DELETE` for every role except the migration owner.

| Column | Type | Rules |
|---|---|---|
| id | text PK | `txn_` ULID |
| workspace_id | text FK workspaces.id, not null | |
| seq | bigint, not null | per-workspace sequence, `unique (workspace_id, seq)` |
| type | text, not null | `top_up`, `call_charge`, `feature_charge`, `trial_grant`, `refund`, `adjustment` |
| amount_usd | numeric(18,6), not null | sign rule below |
| balance_after_usd | numeric(18,6), not null | previous `balance_after_usd + amount_usd` |
| call_id | text null | `call_` id for `call_charge` and call `refund`; FK added by 003 |
| feature_key | text null | for `feature_charge`, e.g. `prompt_generation` |
| external_ref | text null, unique | Stripe payment intent, refund or dispute id |
| idempotency_key | text null | `unique (workspace_id, idempotency_key)` |
| description | text, not null | human-readable, max 200 chars |
| created_by | text null | `usr_` id for admin adjustments, null for system |
| created_at | timestamptz, default now() | |

Sign rules (CHECK constraints): `top_up`, `trial_grant`, `refund` > 0; `call_charge`,
`feature_charge` < 0; `adjustment` != 0.

Partial unique indexes: `(workspace_id) where type = 'trial_grant'`;
`(call_id) where type = 'call_charge'`.

Index: `(workspace_id, seq desc)` serves balance reads and newest-first history.

Derived values:
- Balance = `balance_after_usd` of the row with max `seq` (0 when none). Never stored elsewhere.
- Reconciliation invariant: `sum(amount_usd) = balance`, and each row's `balance_after_usd` equals
  the previous row's plus its amount.

## checkout_sessions

Tracks hosted checkouts so abandoned ones leave an audit trail and webhooks can be matched.

| Column | Type | Rules |
|---|---|---|
| id | bigint identity PK | internal; sent to Stripe as `client_reference_id` |
| workspace_id | text FK, not null | RLS |
| stripe_session_id | text unique, not null | |
| amount_usd | numeric(18,6), not null | 5.00 to 10,000.00 |
| status | text, not null | `pending` > `completed` or `expired` |
| txn_id | text null FK credit_transactions.id | set when completed |
| created_at, completed_at | timestamptz | |

State transitions: `pending -> completed` on paid webhook (same DB transaction as the `top_up` row);
`pending -> expired` on `checkout.session.expired`. A canceled return leaves the row `pending` until
Stripe expires it (24 h); no transaction is written (US2.2).

## pricing_catalog_versions

Global (no RLS). App role read-only.

| Column | Type | Rules |
|---|---|---|
| version | int PK | 1, 2, 3, ... |
| effective_from | timestamptz, not null, unique | must be later than the current version's when published |
| notes | text | |
| published_by | text FK users.id | |
| created_at | timestamptz | |

## pricing_rates (Pricing Catalog Entry)

| Column | Type | Rules |
|---|---|---|
| id | bigint identity PK | |
| version | int FK pricing_catalog_versions, not null | |
| component | text, not null | `stt`, `llm`, `tts`, `nc`, `platform` |
| provider | text, not null | free string, e.g. `deepgram`, `azure_openai`, `callwright` (platform) |
| model | text null | null = provider-level fallback |
| label | text, not null | display name, e.g. "Nova 3" |
| rate_per_min_usd | numeric(18,6), not null, >= 0 | |
| bundles | jsonb, not null, default `[]` | `[{unit, per_min}]`, units `llm_input_tokens`, `llm_output_tokens`, `tts_chars` |

Unique: `(version, component, provider, coalesce(model, ''))`. Validation: `bundles` allowed only for
`llm` and `tts`; exactly one `platform` row per version.

Effective-date range for a version = `[effective_from, next version's effective_from)`.

Seed (migration `0003_pricing_catalog`), version 1, effective at migration time. Rates are the
reference market rates captured live on 2026-10-16 (`research/live/pricing-catalog.json`), with
Callwright provider ids. Every row below is exact; the seed test (T100) asserts the whole set.

| component | provider | model | label | rate_per_min_usd | bundles |
|---|---|---|---|---|---|
| stt | deepgram | null (Auto) | Deepgram, Auto | 0.0085 | |
| stt | deepgram | nova-3 | Nova-3 | 0.0085 | |
| stt | deepgram | nova-2 | Nova-2 | 0.0058 | |
| stt | deepgram | flux-general-en | Flux | 0.0085 | |
| stt | assemblyai | null (Auto) | AssemblyAI, Auto | 0.0030 | |
| stt | assemblyai | universal-streaming | Universal Streaming | 0.0030 | |
| stt | assemblyai | universal-streaming-multilingual | Universal Streaming Multilingual | 0.0030 | |
| stt | sarvam | null (Auto) | Sarvam, Auto | 0.0060 | |
| stt | sarvam | saarika:v2.5 | Saarika v2.5 | 0.0060 | |
| stt | sarvam | saaras:v3 | Saaras v3 | 0.0060 | |
| llm | azure_openai | gpt-5-mini | GPT-5 Mini | 0.0015 | 20,000 `llm_input_tokens`, 200 `llm_output_tokens` |
| llm | azure_openai | gpt-5.1 | GPT-5.1 | 0.0165 | same |
| llm | azure_openai | gpt-5.2 | GPT-5.2 | 0.0315 | same |
| llm | openai | gpt-5-mini | GPT-5 Mini | 0.0015 | same |
| llm | openai | gpt-5.1 | GPT-5.1 | 0.0165 | same |
| llm | openai | gpt-5.2 | GPT-5.2 | 0.0315 | same |
| tts | elevenlabs | eleven_flash_v2_5 | Flash v2.5 | 0.0450 | 750 `tts_chars` |
| tts | elevenlabs | eleven_flash_v2 | Flash v2 | 0.0450 | same |
| tts | elevenlabs | eleven_turbo_v2_5 | Turbo v2.5 | 0.0450 | same |
| tts | elevenlabs | eleven_turbo_v2 | Turbo v2 | 0.0450 | same |
| tts | elevenlabs | eleven_multilingual_v2 | Multilingual v2 | 0.0900 | same |
| tts | cartesia | sonic-2 | Sonic 2 | 0.0275 | same |
| tts | cartesia | sonic-2-2025-03-07 | Sonic 2 (2025-03-07) | 0.0275 | same |
| tts | cartesia | sonic-3 | Sonic 3 | 0.0275 | same |
| tts | cartesia | sonic-turbo | Sonic Turbo | 0.0275 | same |
| tts | fishaudio | s2.1-pro | S2.1 Pro | 0.0150 | same |
| tts | fishaudio | s2-pro | S2 Pro | 0.0150 | same |
| tts | fishaudio | s1 | S1 | 0.0150 | same |
| nc | sanas | vi | Voice isolation | 0.0000 | |
| nc | sanas | st | Standard noise removal | 0.0000 | |
| nc | ai_coustics | standard | Lightweight noise removal | 0.0000 | |
| platform | callwright | null | Callwright platform fee | 0.0500 | |

Rules behind the seed:
- One canonical model id per model across providers (`gpt-5.1` under both `azure_openai` and
  `openai`). Provider deployment names are adapter configuration, never catalog keys. The
  reference product priced Azure rows under a different id (`gpt-5.1-chat`) than its picker used,
  so its builder showed $0.0000 for two models; FR-022 and the 002 consistency test (002 T090)
  prevent that drift.
- Noise cancellation is a priced component at $0.0000 at launch, so it still appears as a line
  in quotes and breakdowns; "off" has no row (config `null`).
- Rows with `model = null` for STT price the "Auto" choice in quotes. A finished call is priced by
  the model the runtime reports in its usage meters (003 resolves Auto per language), falling back
  to the provider row only when no exact model row exists.
- No Sarvam text-to-speech, Anthropic or other vendor rows at launch: the agent builder does not
  offer them, and adding one later is one catalog row plus one adapter (Principle I).
- SC-004's reference call uses Deepgram 0.0085, `gpt-5-mini` 0.0015, ElevenLabs 0.0450 and the
  platform fee 0.0500, all present above.

## call_costs (Cost Breakdown)

One row per priced call, written by `billing.service.charge_call`. RLS.

| Column | Type | Rules |
|---|---|---|
| call_id | text PK | `call_` id (FK to `calls` added by 003) |
| workspace_id | text, not null | |
| catalog_version | int FK pricing_catalog_versions | version in effect at call start |
| duration_ms | bigint, not null, >= 0 | as measured |
| billed_seconds | int, not null | `ceil(duration_ms / 1000)` |
| duration_minutes | numeric(18,6) | `billed_seconds / 60` |
| lines | jsonb, not null | array of CostLine (below) |
| total_usd | numeric(18,6), not null | sum of line `cost_usd` |
| raw_cost_usd | numeric(18,6), not null | sum of unrounded non-platform line costs |
| txn_id | text null | null when `total_usd = 0` |
| created_at | timestamptz | |

CostLine: `{component, provider, model, rate_per_min_usd, billed_minutes, cost_usd, surcharge_usd,
bundle_multiplier, meters: [{unit, used, bundle_per_min, included}]}` where `included =
bundle_per_min × duration_minutes`. An unpriced component makes the whole charge fail with
`pricing_unavailable` and the call stays in `processing` for operator review (it cannot happen for
versions that passed the 002 readiness check).

## usage_events (Usage Row source)

One row per charge. RLS.

| Column | Type | Rules |
|---|---|---|
| id | bigint identity PK | |
| workspace_id | text, not null | |
| feature_key | text, not null | `calls`, `eval.<name>`, `simulator.<step>`, `analytics_chat`, `prompt_generation`, `post_call_analysis` |
| quantity | numeric(18,6), not null | e.g. minutes, judge calls, tokens |
| unit | text, not null | `minutes`, `runs`, `requests`, `tokens` |
| raw_cost_usd | numeric(18,6), not null, >= 0 | |
| billable_cost_usd | numeric(18,6), not null, >= 0 | equals the absolute ledger amount |
| ref_type | text null | `call`, `evaluator_run`, `simulation_run`, `agent`, ... |
| ref_id | text null | |
| txn_id | text null FK credit_transactions.id | null when `billable_cost_usd = 0` (FR-023) |
| occurred_at | timestamptz, not null | |

Zero-amount charges (FR-023, architecture section 7): `charge_feature()` with a billable amount of
0 writes the `usage_events` row (quantity and raw cost kept, `txn_id` null) and no
`credit_transactions` row, because the ledger's sign rule requires `feature_charge < 0`. Idempotency
for such rows uses `unique (workspace_id, feature_key, ref_type, ref_id)` where `txn_id is null`
plus the caller's idempotency key stored in `ref_id` when no natural reference exists.

Index: `(workspace_id, occurred_at)`. Family mapping for the report: prefix before the first dot,
with `eval` shown as `evaluations` and `simulator` as `simulations`.

---

## Redis keys

| Key | Type | TTL | Purpose |
|---|---|---|---|
| `auth:fail:{sha256(email)}` | counter | 15 min | per-account sign-in throttle (5) |
| `auth:failip:{ip}` | counter | 15 min | per-IP throttle (20) |
| `auth:revoked:{session_id}` | flag | access token remaining life | global sign-out |
| `rl:{bucket}:{key}:{window}` | counter | window | generic rate limits (quote endpoint, later features) |

## Relationships

```text
users 1--1 workspaces 1--* credit_transactions *--0..1 call_costs (via call_id)
workspaces 1--* checkout_sessions 0..1--1 credit_transactions
workspaces 1--* usage_events *--1 credit_transactions
pricing_catalog_versions 1--* pricing_rates
pricing_catalog_versions 1--* call_costs
```

## Validation rules traced to requirements

| Rule | Source |
|---|---|
| Top-up amount >= 5.00 (custom), presets 25/100/500/1000 | FR-008, US2 |
| Balance from ledger only | FR-007 |
| Transaction types closed set | FR-006 |
| Whole-second round-up, bundle rule, per-line ceiling | FR-011, research R1 |
| Catalog version stored per call, never re-priced | FR-010, US3.3 |
| Trial grant once per workspace | FR-002 |
| Refuse calls at balance <= 0 (`credit_check`); concurrency limit stored here, counted by 003 | FR-015 |
| Every builder option has an exact rate in the seed; unpriced never shown as $0 | FR-022 |
| Zero-amount feature charge: usage row, no ledger row | FR-023 |
| Workspace name 1 to 80 chars; `recording_default` boolean | FR-017 |
