<!--
Sync Impact Report
- Version: 0.0.0 → 1.0.0 (initial ratification)
- Principles added: I–VII (all new)
- Sections added: Technology & Platform Constraints, Development Workflow & Quality Gates, Governance
- Templates: plan-template.md "Constitution Check" gates map to principles I–VII ✅; spec/tasks templates need no change ✅
- Deferred TODOs: none
-->

# Callwright Constitution

Callwright is a platform for building, running, and continuously improving AI voice agents:
configure an agent (prompt or flow), put it on a phone number, web widget or WhatsApp, and
measure and fix its quality with evaluators, simulations and auto-drafted prompt fixes.

## Core Principles

### I. Provider-Agnostic Voice Pipeline
Every speech-to-text, LLM, text-to-speech and noise-cancellation vendor sits behind an adapter
selected by agent configuration. No feature may hard-code a vendor. Adding a vendor means one
adapter plus one pricing-catalog row, with no schema change. Agent configuration is plain,
versioned data; the runtime reads it and never mutates it.

### II. Latency Is a Feature
Turn latency (end of user speech → first agent audio) is measured on every turn of every call and
stored. Targets: p50 ≤ 800 ms, p95 ≤ 1500 ms on the default stack. Any change on the hot path
(runtime worker, STT/LLM/TTS adapters, tool execution) must show it does not regress p50/p95 on
the benchmark call set before merge.

### III. Every Second Is Metered and Auditable
Each call produces an itemised cost (STT, LLM, TTS, NC, platform) from the versioned pricing
catalog, with duration rounded up to the whole second and bundle surcharges computed
explicitly. Credits move only through an append-only ledger (top-up, call charge, refund,
adjustment); balances are derived, never edited. Money logic is test-first (Principle VII).

### IV. Quality Is Measured, Not Assumed
Every agent change must be verifiable: evaluators score real calls, simulations replay calls
against a variant, and human labels calibrate how far each evaluator can be trusted. A prompt
fix suggested by the system is applied only after validation against stored calls shows it does
not regress pass rates. Evaluator verdicts always keep their rationale and the evaluator version.

### V. Tenant Isolation and Caller Privacy
All data is scoped to a workspace and enforced at the database layer (row-level security), not
only in API code. Recordings and transcripts are encrypted at rest, served through short-lived
signed URLs, and subject to per-workspace retention. Secrets (API keys, SIP credentials,
webhook signing keys) are stored encrypted and never returned in full by any API.

### VI. Simplicity First
Build the smallest thing that satisfies the spec. One backend service plus one voice worker
until load proves otherwise. Prefer managed services and platform features over custom
infrastructure. Every added service, queue or abstraction must name the requirement that forces
it in the plan's Complexity Tracking table.

### VII. Test the Contracts and the Money
API contracts (OpenAPI) are the source of truth for frontend and backend; contract tests fail
on drift. Billing, pricing, evaluator scoring and calibration math are written test-first.
The voice worker has an offline harness that runs a scripted caller against an agent config
without real telephony.

## Technology & Platform Constraints

- **Web app**: React + TypeScript (Vite), TanStack Query, React Router, Tailwind with Radix
  primitives, `@xyflow/react` for flow canvases, `livekit-client` for browser calls.
- **API**: Python 3.12 FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, OpenAPI-first.
- **Data**: PostgreSQL 16 with pgvector (knowledge-base embeddings) and row-level security;
  Redis for job queue (arq) and rate limits; S3-compatible object storage for recordings and
  documents.
- **Voice runtime**: LiveKit Cloud (or self-hosted LiveKit) with a LiveKit Agents (Python)
  worker; LiveKit SIP for inbound/outbound telephony; WhatsApp Business Calling via Meta.
- **Auth**: managed identity provider (Supabase Auth by default) issuing JWTs verified by the API.
- **Payments**: Stripe Checkout for credit top-ups; Stripe webhooks credit the ledger.
- **Observability**: OpenTelemetry traces across API and worker; per-turn latency events
  stored in Postgres for product analytics.

## Development Workflow & Quality Gates

- Every feature starts with `/speckit-specify` → `/speckit-clarify` (if markers remain) →
  `/speckit-plan` → `/speckit-tasks`. No implementation without an approved spec and plan.
- Each plan passes the Constitution Check: vendor behind adapter (I), latency impact stated (II),
  metering impact stated (III), measurability path (IV), tenancy/privacy review (V),
  complexity justified (VI), contract and money tests listed (VII).
- CI runs lint, type checks, unit tests, contract tests and the offline voice harness.
- Database migrations are forward-only and reviewed with the feature.

## Governance

This constitution overrides conflicting conventions in specs, plans and code reviews.
Amendments need a written rationale, a version bump (MAJOR: principle removed or redefined;
MINOR: principle or section added; PATCH: wording), and an update to dependent templates.
Reviewers reject changes that violate a principle without an entry in Complexity Tracking.
Runtime development guidance lives in `CLAUDE.md`.

**Version**: 1.0.0 | **Ratified**: 2026-10-16 | **Last Amended**: 2026-10-16
