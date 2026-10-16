# Implementation Plan: Tools and Knowledge

**Branch**: `005-tools-knowledge` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-tools-knowledge/spec.md`

## Summary

Adds a workspace tool library (end call, transfer call, press digit, HTTP request) that agents
and flow nodes reference by id, with masked secrets, editor test runs, response mapping and
canned responses for simulations; and knowledge bases of PDF/DOCX documents that are ingested
in the background into pgvector and searched live by a system `kb_search` tool within a 300 ms
p95 budget. API modules `tools` and `knowledge` own the library, ingestion and retrieval; the
voice worker's `worker/tools/` package owns execution on the call. Published agent versions
embed resolved tool definitions so the runtime never reads mutable tool rows.

## Technical Context

**Language/Version**: Python 3.12 (API, jobs, voice worker); TypeScript 5 (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, httpx, pgvector
(Python), pypdf, python-docx, tiktoken, jsonschema, boto3 (S3); LiveKit Agents (Python) and
LiveKit server API (SIP transfer, DTMF, room moves); React, TanStack Query, React Router,
Tailwind + Radix, openapi-typescript client
**Storage**: PostgreSQL 16 with pgvector 0.8 and RLS (tools, knowledge_bases, kb_documents,
kb_chunks); `secrets` table (001); S3-compatible storage for documents; Redis for arq queue,
query-embedding cache and rate limits
**Testing**: pytest (unit, contract via schemathesis-style OpenAPI checks, integration with
Postgres and MinIO containers); voice-worker offline harness with scripted callers; benchmark
scripts under `services/voice-worker/tests/harness/bench/`; Vitest + Testing Library for web
**Target Platform**: Linux containers (API and worker); evergreen browsers
**Project Type**: Web application (SPA + API service + voice worker)
**Performance Goals**: kb_search p95 <= 300 ms, hard cap 800 ms; tool dispatch overhead p95 <=
50 ms; HTTP waiting line only after 400 ms; 20 MB PDF ingested within 2 minutes
**Constraints**: No turn-latency p50/p95 regression on the benchmark call set (Principle II);
secrets never leave the API unmasked except to the worker over the internal channel; uploads
<= 20 MiB; HTTP tool timeout 1 to 30 s (default 8 s); response cap 64 KB
**Scale/Scope**: v1 targets 1,000 workspaces, 25 tools and 10 KBs per agent, 200 documents per
KB, 1 GiB documents per workspace (about 2 M chunks platform-wide)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|---|---|---|
| I. Vendor behind adapter | Pass | Embedding vendors behind `knowledge/embeddings/<vendor>.py` (R13). Telephony actions use LiveKit SIP primitives only, no carrier API (R8, R9). Tool definitions are plain data embedded in the AgentVersion snapshot; the worker never mutates them (R2). |
| II. Latency stated | Pass | Hot-path work: tool dispatch (p95 <= 50 ms overhead), kb_search (p95 <= 300 ms, cap 800 ms), waiting line after 400 ms. Benchmarks and baseline comparison in R21; tasks T021, T041, T073, T091. Secrets fetched once per call, not per turn (R3). |
| III. Metering stated | Pass | Ingestion embeddings charged via `billing.charge_feature("knowledge_ingestion")` (R13). kb_search query cost recorded as a usage meter on the `tool_call` event, not billed in v1 (spec assumption). Transfer: billed duration ends when the agent leaves (R8). Editor test runs are free and rate-limited. |
| IV. Measurability | Pass | Every invocation is a `tool_call` CallEvent with outcome and timing (R19), feeding 007 evaluators (tool-call correctness, KB relevance). SC-007 retrieval accuracy set checked in CI. Canned responses enable 008 simulations. |
| V. Tenancy and privacy | Pass | All four new tables carry `workspace_id` with RLS. Internal search derives the workspace from `call_id` and sets `app.workspace_id`. Secrets encrypted, masked, never in snapshots, transcripts, events or logs (FR-024 to FR-026). Documents encrypted at rest, 10-minute signed URLs. SSRF guard (R4). |
| VI. Simplicity | Pass with notes | No new service: ingestion runs in the existing arq worker; vector search in Postgres; uploads through the API. One small duplication (HTTP core in API and worker) recorded in R5 instead of a shared package. |
| VII. Contracts and money tests | Pass | `contracts/tools.yaml` and `contracts/knowledge.yaml` with contract tests written before routers (T016, T034, T052, T069, T082). Ingestion charge amount test-first (T055). Worker harness scenarios for each tool type (T020, T040, T074, T084). |

Post-design re-check (after Phase 1): unchanged, all gates pass. No Complexity Tracking entries
are required.

## Project Structure

### Documentation (this feature)

```text
specs/005-tools-knowledge/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── tools.yaml
│   └── knowledge.yaml
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/
├── core/secrets.py                 # from 001: encrypt, decrypt, mask (used, not owned)
├── tools/
│   ├── router.py                   # /v1/tools, /v1/agents/{id}/tools, internal tool-secrets
│   ├── schemas.py                  # ToolSpec, HttpRequestSpec, TransferSpec (shared with 004)
│   ├── models.py                   # Tool ORM
│   ├── service.py                  # CRUD, attach, usages, resolve_for_snapshot, mock coverage
│   ├── validation.py               # names, reserved names, E.164, JSON Schema, URL rules
│   └── http_exec.py                # editor test-run executor + address guard (R4, R5)
├── knowledge/
│   ├── router.py                   # /v1/knowledge-bases..., /v1/agents/{id}/knowledge-bases, internal search
│   ├── schemas.py
│   ├── models.py                   # KnowledgeBase, Document, Chunk ORM
│   ├── service.py                  # CRUD, duplicates, attach, delete-detach, search
│   ├── storage.py                  # S3 keys, put, delete, presign
│   ├── extract.py                  # PDF and DOCX text extraction, content sniffing
│   ├── chunking.py                 # heading-aware splitter
│   ├── embeddings/{base,openai,azure_openai}.py
│   └── jobs.py                     # ingest_document arq job
└── migrations/versions/005_tools_knowledge.py

services/api/tests/
├── contract/test_tools_contract.py
├── contract/test_knowledge_contract.py
├── unit/ (validation, http_exec vectors, chunking, extract, masking, ingestion charge)
└── integration/ (attach + publish snapshot, delete-detach, ingestion end to end, RLS)

services/voice-worker/worker/tools/
├── base.py                         # ToolExecutor protocol, ToolResult, ToolContext
├── registry.py                     # builds LLM function tools from the snapshot, dispatch, events
├── secrets.py                      # one fetch per call of tool secrets
├── end_call.py
├── transfer.py
├── dtmf.py
├── http.py
└── kb_search.py
services/voice-worker/tests/
├── unit/ (registry, http vectors, transfer state machine, dtmf cooldown)
└── harness/
    ├── scenarios/tools_*.yaml, kb_*.yaml
    └── bench/{bench_tool_dispatch.py, bench_kb_search.py, bench_call_set_tools.py, baseline.json}

apps/web/src/routes/
├── agents/tools/                   # agent Tools tab: list, attach, editor dialogs, test run
└── knowledge/                      # /knowledge-base list, KB detail, upload, preview search
```

**Structure Decision**: Follows `research/architecture.md` sections 2 and 3: API modules
`tools` and `knowledge` (005 ownership), worker executors under `worker/tools/`, web routes
`/knowledge-base` and the agent tools tab. `HttpRequestSpec` and `TransferSpec` in
`tools/schemas.py` are imported by 004's `flows` module for webhook and transfer nodes, and
004's node handlers call `worker/tools/http.py`, `transfer.py` and `end_call.py`.

## Cross-feature interfaces

| Interface | Direction | Notes |
|---|---|---|
| `tools.service.resolve_for_snapshot(workspace_id, tool_ids) -> list[ToolSpec]` | 005 to 002, 004 | Called at publish and flow compile; secrets as `secret_ref` |
| `agents.service.update_draft(agent_id, patch)` | 002 to 005 | Used by `PUT /v1/agents/{id}/tools` and `/knowledge-bases` |
| `AgentConfig.tool_ids[]`, `AgentConfig.kb_ids[]` | 002 schema | 005 validates contents |
| `POST /v1/internal/calls/{call_id}/events` kind `tool_call` | 005 worker to 003 | Payload in data-model.md |
| `GET /v1/internal/calls/{call_id}/tool-secrets` | worker to 005 | Service token; resolves refs found in the call's snapshot |
| `POST /v1/internal/knowledge/search` | worker to 005 | Service token; RLS via call's workspace |
| Session config `simulation: true` | 008 to worker | Switches tools to mocks |
| `billing.charge_feature("knowledge_ingestion", ...)` | 005 to 001 | Ingestion cost |
| Flow webhook node `mock_response`, `kb_search_enabled` per node | 004 | Mock coverage asks 004 for webhook nodes lacking mocks |

## Complexity Tracking

No constitution violations. Noted trade-off (not a violation): HTTP execution logic duplicated
between `services/api/app/tools/http_exec.py` and `services/voice-worker/worker/tools/http.py`,
kept in step by shared test vectors (research R5).
