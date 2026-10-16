# Implementation Plan: Agent Builder

**Branch**: `002-agent-builder` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/002-agent-builder/spec.md`

## Summary

Single-prompt agents on one versioned `AgentConfig` document (a deliberate merge of the reference
product's separate LLM and agent records, research R1). The agent row holds a mutable draft;
every changing save records an immutable `AgentVersion`; publishing pins one version for live
channels; restore and compare work on versions; test calls get deduplicated snapshots. Options
come from capability YAML joined with 001's pricing catalog, so vendors stay data (Principle I).
The editor shows a live cost estimate from 001's quote endpoint, offers industry templates, and
has a charged, stateless AI prompt assistant.

## Technical Context

**Language/Version**: Python 3.12 (API), TypeScript 5.x (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, `httpx` (vendor voice
listings and assistant model calls), `PyYAML` (catalog and template seeds), `python-magic`
(upload sniffing); web: React 18, TanStack Query, React Router, Tailwind + Radix,
`react-hook-form` (editor state), `diff` (text diffs in version compare)
**Storage**: PostgreSQL 16 (`agents`, `agent_versions`, `templates`, `ambient_audio_files`; RLS;
`pg_trgm` and `jsonb_path_ops` GIN indexes), Redis (voice list cache, assistant rate limit),
S3-compatible storage (ambient audio uploads)
**Testing**: pytest (unit, contract with openapi-core per 001 R16, integration against compose
Postgres/Redis/MinIO), vendor listing adapters tested against recorded fixtures; web: Vitest +
Testing Library, Playwright for the create, version and template journeys
**Target Platform**: `services/api` container (HTTP and arq worker); SPA on CDN
**Project Type**: Web application (SPA + API), research/architecture.md section 2
**Performance Goals**: list with search p95 under 300 ms at 1,000 agents (SC-005 asks 1 s);
draft save p95 under 400 ms including version insert; cost card refresh under 1 s end to end
(SC-002); publish visible to the next admission immediately (SC-006)
**Constraints**: versions immutable (DB trigger); providers and models never enums; prompts and
webhook URLs are workspace data under RLS; assistant requests charged and rate-limited
**Scale/Scope**: up to 1,000 agents and 100,000 versions per workspace; 9 template categories;
6 API modules, 25 operations; 6 web screens (chooser, template picker, editor with 4 sections,
version drawer and compare view, agent list, assistant panel)

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design (no changes).*

| Gate | Principle | Status | Evidence |
|---|---|---|---|
| Vendor behind adapter | I | PASS | AgentConfig stores provider/model strings validated against catalog YAML plus 001 pricing; no enums in contracts (R6). Voice listings go through `voices/adapters/<vendor>.py`; assistant calls through `llms/client.py` and `llms/adapters/<vendor>.py`. A new vendor is a runtime adapter (003), a capability entry, a pricing row. Configs are plain data, versions immutable, the runtime only reads them. |
| Latency impact stated | II | PASS | No per-turn code. At call start 003 reads `agents.pinned_version_id` (indexed) and the immutable version (cacheable by id). Pronunciation, background audio and DTMF settings are consumed by 003, whose plan covers their hot-path cost. |
| Metering impact stated | III | PASS | Cost card uses 001's `POST /v1/pricing/quote` (no second pricing implementation). Assistant requests go through `billing.charge_feature("prompt_generation")`. `advanced.analysis_model` changes post-call cost in 007; the card notes it. Unpriced components block publishing, so no live call can run unpriced. |
| Measurability path | IV | PASS | Every call references an `agv_` version; diffs between versions explain behaviour changes; 007/008 compare pass rates per version; 008 validates variants with `validate_config`. |
| Tenancy and privacy review | V | PASS | RLS on `agents`, `agent_versions`, `ambient_audio_files`; templates global read-only. Vendor API keys for voice listing stay server-side (secrets table). Webhook URLs restricted to public HTTPS hosts (R20). Uploads encrypted at rest, served by 10-minute signed URLs. Assistant sends prompt text to the platform model vendor; documented in the privacy policy (001). |
| Complexity justified | VI | PASS | No new service or queue. Catalog as YAML, not tables. Assistant stateless. Ambient uploads reuse the existing object store. |
| Contract and money tests listed | VII | PASS | Contract tests for all 6 contract files; money tests: assistant charge (one `feature_charge` per successful request, none on timeout or refusal), cost card parity (editor total equals 001 quote total for the same selection). Validation rules unit-tested from the data-model table. |

## Project Structure

### Documentation (this feature)

```text
specs/002-agent-builder/
├── spec.md
├── plan.md              # This file
├── research.md          # R1 to R24
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── agents.yaml          # agents CRUD, defaults, validate, draft save, duplicate; AgentConfig schema
│   ├── agent_versions.yaml  # list, detail, diff, restore, publish, unpublish
│   ├── templates.yaml
│   ├── llms.yaml
│   ├── voices.yaml          # speech catalog, voice browser, ambient audio uploads
│   └── prompt_ai.yaml
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/
├── agents/
│   ├── router.py            # /v1/agents, /defaults, /validate, /{id}, /{id}/draft, /{id}/duplicate
│   ├── schemas.py           # AgentConfig v1 Pydantic models, upcasters, API schemas
│   ├── models.py            # Agent
│   ├── service.py           # create_agent, update_draft, rename, duplicate, delete_agent, validate_config, list/search
│   ├── defaults.py          # platform defaults (research R23)
│   ├── variables.py         # placeholder extraction, reserved names
│   ├── hooks.py             # validator, snapshot-resolver, usage-checker and duplicate registries (R5, R14, R15)
│   └── webhook_url.py       # https and public-address checks (R20)
├── agent_versions/
│   ├── router.py
│   ├── schemas.py
│   ├── models.py            # AgentVersion
│   ├── service.py           # create_version, snapshot_for_test, publish, unpublish, restore, list, get
│   ├── canonical.py         # canonical JSON + sha256 (R3)
│   └── diff.py              # keyed diff (R12)
├── templates/
│   ├── router.py  schemas.py  models.py  service.py
│   ├── jobs.py              # sync seed YAML into the templates table on deploy
│   └── seed/*.yaml          # at least one template per category
├── llms/
│   ├── router.py  schemas.py  service.py
│   ├── catalog.yaml         # providers, models, temperature rules
│   ├── client.py            # API-side model gateway (assistant; reusable by 006/007/008)
│   └── adapters/{azure_openai,openai,anthropic}.py
├── voices/
│   ├── router.py  schemas.py  models.py  service.py
│   ├── catalog.yaml         # languages + defaults, STT, TTS, NC, ambient sounds
│   └── adapters/{elevenlabs,cartesia,fishaudio,sarvam}.py   # voice listing only
├── prompt_ai/
│   ├── router.py  schemas.py  service.py
│   └── system_prompt.md     # assistant instructions (versioned with code)
└── migrations/versions/0005_agents.py, 0006_templates.py, 0007_ambient_audio.py

services/api/tests/
├── unit/agents/  unit/agent_versions/  unit/llms/  unit/voices/  unit/prompt_ai/
├── contract/test_{agents,agent_versions,templates,llms,voices,prompt_ai}_contract.py
└── integration/agents/  integration/agent_versions/  integration/templates/  integration/prompt_ai/

apps/web/src/routes/agents/
├── AgentsListPage.tsx  AgentCard.tsx
├── NewAgentTypePage.tsx                  # /agents/new
├── TemplatesPage.tsx  TemplatePreviewDialog.tsx   # /agents/templates
├── editor/
│   ├── AgentEditorPage.tsx               # /agents/new/single and /agents/:id/edit
│   ├── useAgentDraft.ts                  # react-hook-form + validate + save with If-Match
│   ├── BasicSection.tsx  VoiceSection.tsx  CallBehaviorSection.tsx  AdvancedSection.tsx
│   ├── ModelPicker.tsx  TemperatureControl.tsx  VariablesEditor.tsx
│   ├── VoicePickerDialog.tsx  SttPickerDialog.tsx  NoiseCancellationSelect.tsx
│   ├── BackgroundAudioField.tsx  PronunciationEditor.tsx  WebhookField.tsx
│   ├── CostCard.tsx  surchargeRisk.ts
│   └── AssistantPanel.tsx
├── versions/
│   ├── VersionDrawer.tsx  VersionCompare.tsx  versionLabels.ts  PublishButton.tsx
└── agentRedirect.tsx                      # /agents/:id -> /edit or /flow by type
```

**Structure Decision**: Module names from architecture section 3 (agents, agent_versions,
templates, llms, voices, prompt_ai) with the standard `router/schemas/models/service/jobs` files.
Extra single-purpose files (`defaults.py`, `variables.py`, `hooks.py`, `webhook_url.py`,
`canonical.py`, `diff.py`, catalog YAML, vendor listing adapters) keep pure logic testable
without a database.

## Phase 0: Research

All decisions in [research.md](./research.md). Highlights: R1 merged AgentConfig; R2 draft plus
snapshot-on-save plus explicit publish; R5 extension blocks and hooks for 004, 005, 007; R6
catalog as YAML joined with pricing; R10 one validator with errors, publish blockers, warnings;
R12 keyed diff; R17 cost card via 001 quote with a surcharge-risk heuristic.

## Phase 1: Design

- [data-model.md](./data-model.md): tables, AgentConfig v1 field table with ranges and defaults,
  state rules, validation codes, catalog shapes.
- [contracts/](./contracts/): 6 fragments, 25 operations, referencing 001's `core.yaml`.
- [quickstart.md](./quickstart.md): API and UI walk-through for all six stories.

### Interfaces exposed to other features (in-process, same API codebase)

| Function | Caller | Notes |
|---|---|---|
| `agents.service.create_agent(ws, name, type, language, config=None, template_id=None)` | 004 flow create | records version 1 |
| `agents.service.update_draft(ws, agent_id, patch, expected_revision=None, note=None)` | 005 tool/KB attach, 007 evals config | validates, records a version when changed |
| `agents.service.validate_config(type, config, agent_id=None) -> ConfigValidationResult` | 004 global settings, 008 variants | same code as save |
| `agents.hooks.register_validator / register_snapshot_resolver / register_usage_checker / register_duplicate_hook` | 004, 005, 007, 010 | R5, R14, R15 |
| `agent_versions.service.create_version(agent_id, config, note, source, publish=False)` | 004 flow publish | dedupes by hash |
| `agent_versions.service.snapshot_for_test(agent_id) -> AgentVersion` | 003 draft test calls | never publishes |
| `agent_versions.service.get_published(agent_id) -> AgentVersion or None` | 003 admission, 010 routing | one indexed read |
| `agent_versions.service.get(version_id) -> AgentVersion` | 003 claim, 006 call detail, 008 | works for deleted agents |
| `llms.client.complete(model_ref, messages, ...)` | 006, 007, 008 (optional) | API-side model gateway |
| `agents.service.validate_override(path, value) -> list[ConfigIssue]` | 004 flow node overrides | same `controls` ranges and steps as the agent (FR-047, T104) |
| `apps/web/src/routes/agents/editor/panelSlots.ts` `registerEditorPanel(id, component)` | 007 analysis variables and quality checks panels | web-side slot for both agent types (FR-043, T097) |
| `voices.service.resolve_auto_stt(provider, language) -> model` | 003 worker claim (RuntimeConfig) | applies the catalog `auto_rule` (data-model 8.3) |

### Dependencies on 001

`core.auth.current_workspace`, RLS session, `billing.service.charge_feature`,
`billing.service.get_balance`, `pricing.service.quote` (catalog prices for pickers),
`POST /v1/pricing/quote` (cost card), 001's `LeaveGuard` and `ErrorSummaryDialog` components.

## Complexity Tracking

No constitution violations. Items for reviewers:

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `llms/client.py` + `llms/adapters/` in the API (architecture lists vendor adapters only under the worker) | The assistant (and later judges, analytics chat) call models from the API process | Routing assistant calls through the voice worker would put a non-call workload on the call path |
| `voices/adapters/` for voice listing | Vendor voice lists differ in shape and paging; keys must stay server-side | Client-side per-vendor calls expose keys and duplicate logic (reference product did per-vendor endpoints) |
| Hook registries in `agents/hooks.py` | 004, 005, 007, 010 must validate, snapshot and guard their own blocks without 002 importing them | Hard-coding calls from 002 into later modules inverts the dependency order in architecture section 3 |
| `agents.draft_config` stored alongside versions (draft equals the latest saved version's config, minus snapshot-only blocks) | Architecture section 5 names a draft; 005 scans drafts; 004 extends drafts with flow data | Pointer-only drafts would force every editor load through a version join and complicate 005's draft usage lookup |
