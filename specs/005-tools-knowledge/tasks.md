---

description: "Task list for 005-tools-knowledge"
---

# Tasks: Tools and Knowledge

**Input**: Design documents from `/specs/005-tools-knowledge/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/tools.yaml,
contracts/knowledge.yaml, quickstart.md

**Tests**: Required. Constitution Principle VII (contract tests before implementation, money
logic test-first, offline voice harness) and Principle II (latency benchmarks for hot-path
changes: tool execution and kb_search).

**Organization**: Grouped by user story (US1 to US5 from spec.md). Depends on 001 (core, auth,
billing, secrets), 002 (agents, agent_versions) and 003 (calls, call_events, worker pipeline).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US5; Setup, Foundational and Polish tasks carry no story label

---

## Phase 1: Setup

- [ ] T001 Create module packages `services/api/app/tools/__init__.py`, `services/api/app/knowledge/__init__.py` and `services/api/app/knowledge/embeddings/__init__.py`
- [ ] T002 [P] Add API dependencies (httpx, pgvector, pypdf, python-docx, tiktoken, jsonschema) to `services/api/pyproject.toml`
- [ ] T003 [P] Create `services/voice-worker/worker/tools/__init__.py` and `services/voice-worker/tests/harness/bench/__init__.py` with an empty `services/voice-worker/tests/harness/bench/baseline.json`
- [ ] T004 [P] Add knowledge fixtures in `services/api/tests/fixtures/knowledge/` (refund_policy.pdf with a "14 days" refund clause, policies.docx with headings and a table, scanned.pdf, encrypted.pdf, notes_renamed.pdf, `make_oversize.py` generating a 21 MB file at test time)
- [ ] T005 [P] Register web routes `/knowledge-base` (`apps/web/src/routes/knowledge/index.tsx`) and the agent Tools tab (`apps/web/src/routes/agents/tools/index.tsx`) in `apps/web/src/app/router.tsx`

---

## Phase 2: Foundational (blocks all stories)

- [ ] T006 Write migration `services/api/app/migrations/versions/005_tools_knowledge.py`: tables `tools`, `knowledge_bases`, `kb_documents`, `kb_chunks` per data-model.md, `vector` extension check, HNSW index (`vector_cosine_ops`, m 16, ef_construction 64), unique `(kb_id, sha256)`, RLS policies on `workspace_id`
- [ ] T007 [P] RLS isolation test across two workspaces for all four tables in `services/api/tests/integration/test_tools_knowledge_rls.py`
- [ ] T008 [P] Shared Pydantic schemas in `services/api/app/tools/schemas.py`: ToolType, ToolName, EndCallConfig, TransferSpec, PressDigitConfig, HeaderSpec, ResponseMapping, HttpRequestSpec, HttpToolConfig, ToolConfig discriminated union, ToolSpec (snapshot form); export HttpRequestSpec and TransferSpec for 004
- [ ] T009 [P] Validation unit tests (name pattern, reserved `kb_search` and `route_to_` prefix, E.164, parameters must be JSON Schema type object with depth and size limits, https rule outside development, header names) in `services/api/tests/unit/test_tool_validation.py`
- [ ] T010 Implement `services/api/app/tools/validation.py` to pass T009 (depends on T008)
- [ ] T011 [P] Worker base types in `services/voice-worker/worker/tools/base.py`: ToolExecutor protocol, ToolContext (call_id, channel, simulation flag, variable store, secret map, turn_index, say callback), ToolResult (llm_payload, is_error, error_code, output, mocked)
- [ ] T012 Worker registry skeleton in `services/voice-worker/worker/tools/registry.py`: build LLM function tools from the snapshot `tools[]`, validate arguments against `parameters`, time each dispatch (duration_ms, dispatch_overhead_ms), emit `tool_call` events through `services/voice-worker/worker/metrics.py` without blocking; wire into `services/voice-worker/worker/pipeline.py`
- [ ] T013 [P] Registry unit tests (function shapes per type, argument validation error path, event emission non-blocking) in `services/voice-worker/tests/unit/test_tool_registry.py`
- [ ] T014 [P] Merge `specs/005-tools-knowledge/contracts/tools.yaml` and `knowledge.yaml` into `contracts/openapi.yaml` and regenerate the TS client in `apps/web/src/api/`
- [ ] T015 Mount `tools` and `knowledge` routers in the API app factory `services/api/app/main.py`

**Checkpoint**: schema, shared types and worker registry exist; stories can start.

---

## Phase 3: User Story 1 - Call-control tools (Priority: P1) MVP

**Goal**: Workspace tool library with end_call, transfer_call and press_digit, attachable to
agents and executed on phone calls.

**Independent Test**: Quickstart section 1: attach end-call and cold transfer tools, run the
harness scenarios, confirm `agent_hangup` and `call_transfer` outcomes and `tool_call` events.

### Tests for User Story 1 (write first, must fail)

- [ ] T016 [P] [US1] Contract tests for `/v1/tools` CRUD, duplicate, usages, `PUT|GET /v1/agents/{agent_id}/tools` (25 limit, `tool_name_conflict`) and delete `tool_in_use` in `services/api/tests/contract/test_tools_contract.py`
- [ ] T017 [P] [US1] Integration test: attach, publish (snapshot embeds ToolSpec), edit tool, confirm published version unchanged, delete with `force` detaches drafts only, in `services/api/tests/integration/test_tools_attach_publish.py`
- [ ] T018 [P] [US1] Worker unit tests for transfer (static, dynamic with allow-list, cold, warm private and public, ring timeout failure, non-SIP channel) in `services/voice-worker/tests/unit/test_transfer.py`
- [ ] T019 [P] [US1] Worker unit tests for press digit (digit pattern, delay, cooldown delays instead of drops) and end call (message then hangup reason) in `services/voice-worker/tests/unit/test_dtmf_end_call.py`
- [ ] T020 [P] [US1] Harness scenarios `tools_end_call.yaml`, `tools_transfer_cold.yaml`, `tools_transfer_warm.yaml`, `tools_press_digit.yaml`, `tools_transfer_web_unsupported.yaml` in `services/voice-worker/tests/harness/scenarios/`
- [ ] T021 [P] [US1] Latency benchmark for tool dispatch overhead (end_call, press_digit and a 0 ms in-process stub tool; 500 iterations; gate p95 <= 50 ms) in `services/voice-worker/tests/harness/bench/bench_tool_dispatch.py`

### Implementation for User Story 1

- [ ] T022 [P] [US1] Tool ORM model in `services/api/app/tools/models.py`
- [ ] T023 [US1] Tools service in `services/api/app/tools/service.py`: create, list (type, search, pagination), get, patch (type immutable), duplicate, delete with force-detach, usages (drafts and published versions via agents and agent_versions services), attach set validation and `agents.service.update_draft`, `resolve_for_snapshot(workspace_id, tool_ids)`
- [ ] T024 [US1] Tools router in `services/api/app/tools/router.py`: `/v1/tools`, `/v1/tools/{tool_id}`, `/duplicate`, `/usages`, `GET|PUT /v1/agents/{agent_id}/tools`
- [ ] T025 [US1] Call `tools.service.resolve_for_snapshot` from the publish path in `services/api/app/agent_versions/service.py` (coordinate with 002 owner; snapshot field `tools`)
- [ ] T026 [P] [US1] End-call executor in `services/voice-worker/worker/tools/end_call.py` (speak message, hang up with `agent_hangup`)
- [ ] T027 [P] [US1] Transfer executor in `services/voice-worker/worker/tools/transfer.py` (SIP REFER cold; warm via consult room, CreateSIPParticipant, briefing static or one LLM line, MoveParticipant; public variant dials into caller room; hold message; disconnect reason `call_transfer`; failure returns to LLM)
- [ ] T028 [P] [US1] Press-digit executor in `services/voice-worker/worker/tools/dtmf.py` (publish_dtmf per digit, delay_ms, cooldown_ms)
- [ ] T029 [US1] Register the three executors and SIP-only channel gating (`channel_unsupported`) in `services/voice-worker/worker/tools/registry.py`
- [ ] T030 [P] [US1] Tools tab list and attach dialog in `apps/web/src/routes/agents/tools/ToolsTab.tsx` and `apps/web/src/routes/agents/tools/AttachToolsDialog.tsx`, data hooks in `apps/web/src/routes/agents/tools/useTools.ts`
- [ ] T031 [P] [US1] Type forms `EndCallForm.tsx`, `TransferForm.tsx` (static or dynamic, allowed numbers, cold or warm, briefing, hold message, ring timeout), `PressDigitForm.tsx` in `apps/web/src/routes/agents/tools/forms/`
- [ ] T032 [US1] Tool editor dialog with type picker, name placeholders, inline name errors and "used by N agents" notice in `apps/web/src/routes/agents/tools/ToolEditorDialog.tsx`
- [ ] T033 [P] [US1] Component tests in `apps/web/src/routes/agents/tools/ToolsTab.test.tsx`
- [ ] T093 [P] [US1] Extend `services/api/tests/contract/test_tools_contract.py` with `GET /v1/tools/presets`, 422 naming the field for unknown or outdated config keys (a legacy transfer block next to the current one), and 422 for `mock_response` on non-http types
- [ ] T094 [US1] Preset constants in `services/api/app/tools/presets.py`, the presets endpoint in `services/api/app/tools/router.py`, and `extra = "forbid"` on every config model in `services/api/app/tools/schemas.py` (makes T093 pass)
- [ ] T095 [P] [US1] Preset picker in the new-tool dialog and inline field checks (E.164, required fields named, Save disabled while invalid) in `apps/web/src/routes/agents/tools/ToolEditorDialog.tsx` and `apps/web/src/routes/agents/tools/forms/fieldRules.ts`

**Checkpoint**: US1 independently testable via quickstart section 1.

---

## Phase 4: User Story 2 - Custom HTTP tools (Priority: P1)

**Goal**: HTTP tool with parameters schema, templating, masked secret headers, response
mapping, waiting line, address guard and editor test runs.

**Independent Test**: Quickstart section 2.

### Tests for User Story 2 (write first, must fail)

- [ ] T034 [US2] Extend `services/api/tests/contract/test_tools_contract.py` with `POST /v1/tools/test-run` (saved and inline, 429 limit), secret masking on read, keep-on-patch, and `GET /v1/internal/calls/{call_id}/tool-secrets` (service token, only live calls)
- [ ] T035 [P] [US2] Shared HTTP test vectors `services/api/tests/unit/fixtures/http_exec_vectors.json` (templating order, JSON-safe substitution, GET query placement, mapping paths, missing paths, truncation) with an identical copy at `services/voice-worker/tests/unit/fixtures/http_exec_vectors.json`, and a CI check that both copies match
- [ ] T036 [P] [US2] API executor unit tests driven by the vectors in `services/api/tests/unit/test_http_exec.py`
- [ ] T037 [P] [US2] Address guard tests (RFC 1918, loopback, link-local, metadata v4 and v6, CGNAT, DNS rebinding, redirect to private, 64 KB cap, https rule) in `services/api/tests/unit/test_address_guard.py`
- [ ] T038 [P] [US2] Secret handling tests (encrypt on create, mask `****` + last 4, keep on patch without value, replace, switch to non-secret, scrub from outputs) in `services/api/tests/unit/test_tool_secrets.py`
- [ ] T039 [P] [US2] Worker HTTP executor tests using the vectors plus timeout, no retry, waiting line after 400 ms only, mapped variables written to the call store in `services/voice-worker/tests/unit/test_http_tool.py`
- [ ] T040 [P] [US2] Harness scenarios `tools_http_mapping.yaml`, `tools_http_timeout.yaml`, `tools_http_slow_filler.yaml` in `services/voice-worker/tests/harness/scenarios/` with a local stub server in `services/voice-worker/tests/harness/stubs/http_stub.py`
- [ ] T041 [P] [US2] Latency benchmark for the HTTP tool path (stub at 0 ms: overhead p95 <= 50 ms; stub at 1,500 ms: waiting line starts within 450 ms and fires once) in `services/voice-worker/tests/harness/bench/bench_http_tool.py`

### Implementation for User Story 2

- [ ] T042 [US2] Secret header lifecycle in `services/api/app/tools/service.py` using `services/api/app/core/secrets.py` (write, keep, replace, delete, masked read, secret_ref in snapshots)
- [ ] T043 [US2] Editor executor in `services/api/app/tools/http_exec.py` (templating, argument placement, guarded transport with pinned IP, manual redirects max 3, 64 KB cap, mapping, llm_payload)
- [ ] T044 [US2] `POST /v1/tools/test-run` with Redis token bucket 30 per minute per workspace in `services/api/app/tools/router.py`
- [ ] T045 [US2] `GET /v1/internal/calls/{call_id}/tool-secrets` (service token, call status check, resolves refs in the call's snapshot, never logged) in `services/api/app/tools/router.py`
- [ ] T046 [P] [US2] Per-call secret fetch at session start, in-memory map and scrub helper in `services/voice-worker/worker/tools/secrets.py`; call it from `services/voice-worker/worker/entry.py`
- [ ] T047 [US2] Worker HTTP executor in `services/voice-worker/worker/tools/http.py` (shared logic per vectors, execution_message after 400 ms via say without adding to LLM context, error codes, mapped variables into the call variable store)
- [ ] T048 [US2] Register the HTTP executor and keep-alive client lifecycle in `services/voice-worker/worker/tools/registry.py`
- [ ] T049 [P] [US2] HTTP tool form with method, URL, JSON Schema parameters editor with an example template, body template, timeout, mappings editor, waiting line in `apps/web/src/routes/agents/tools/forms/HttpToolForm.tsx`
- [ ] T050 [P] [US2] Secret header input showing masked value and "replace" action in `apps/web/src/routes/agents/tools/forms/SecretHeaderInput.tsx`
- [ ] T051 [US2] Test-run panel (arguments, variables, status, timing, masked request, response, mapped variables, agent payload) in `apps/web/src/routes/agents/tools/TestRunPanel.tsx`
- [ ] T096 [P] [US2] Shared `HttpRequestFields` component (method list GET, POST, PUT, PATCH, DELETE, timeout 1 to 30 s, headers, body template, mappings, waiting-line toggle, inline absolute https URL check) in `apps/web/src/routes/agents/tools/forms/HttpRequestFields.tsx`, used by `HttpToolForm.tsx` and by 004's webhook node form

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: User Story 3 - Knowledge documents (Priority: P2)

**Goal**: Knowledge bases with PDF/DOCX upload, duplicate detection, background ingestion into
pgvector, status, preview URLs, replace and delete.

**Independent Test**: Quickstart section 3.

### Tests for User Story 3 (write first, must fail)

- [ ] T052 [P] [US3] Contract tests for `/v1/knowledge-bases` CRUD, document upload (202, 409, 413, 415, 422), check-duplicate verdicts, get, delete, reprocess, signed URL in `services/api/tests/contract/test_knowledge_contract.py`
- [ ] T053 [P] [US3] Extraction tests (content sniffing, PDF pages, DOCX headings and tables, scanned `no_extractable_text`, encrypted, corrupt) in `services/api/tests/unit/test_knowledge_extract.py`
- [ ] T054 [P] [US3] Chunking tests (target 400 tokens, 60 overlap, headings kept, tables not split mid-row, page ranges, 5,000-chunk cap) in `services/api/tests/unit/test_knowledge_chunking.py`
- [ ] T055 [P] [US3] Money test-first: ingestion charge = embedded tokens x catalog rate, posted once per document version via `billing.charge_feature("knowledge_ingestion")`, none on failure, in `services/api/tests/unit/test_ingestion_charge.py`
- [ ] T056 [P] [US3] Integration test with a fake embedding adapter: upload to ready, retry idempotency (no duplicate chunks), transient failure backoff to failed, replace swap, quota refusal, per-workspace concurrency of 2, in `services/api/tests/integration/test_knowledge_ingestion.py`

### Implementation for User Story 3

- [ ] T057 [P] [US3] ORM models KnowledgeBase, Document, Chunk in `services/api/app/knowledge/models.py`
- [ ] T058 [P] [US3] Schemas incl. derived KB status and attachable flag in `services/api/app/knowledge/schemas.py`
- [ ] T059 [P] [US3] Object storage helper (key layout, put with SSE, delete, presign 10 minutes inline) in `services/api/app/knowledge/storage.py`
- [ ] T060 [P] [US3] Extraction and content sniffing in `services/api/app/knowledge/extract.py`
- [ ] T061 [P] [US3] Heading-aware chunker in `services/api/app/knowledge/chunking.py`
- [ ] T062 [P] [US3] Embedding adapters `base.py`, `openai.py`, `azure_openai.py` and a test `fake.py` in `services/api/app/knowledge/embeddings/`, plus the embedding pricing catalog seed row (001 catalog)
- [ ] T063 [US3] Knowledge service in `services/api/app/knowledge/service.py`: KB CRUD, duplicate check, streaming upload with 20 MiB cap, sniffing, SHA-256, quotas, delete document, delete KB with detach via `agents.service.update_draft`, reprocess, signed URL
- [ ] T064 [US3] Ingestion job `ingest_document(doc_id)` (Redis semaphore, retries 10 s/60 s/300 s, transactional chunk replace, replace swap, `billing.charge_feature`) in `services/api/app/knowledge/jobs.py`; register in the arq worker settings
- [ ] T065 [US3] Knowledge router (KB and document endpoints from contracts/knowledge.yaml) in `services/api/app/knowledge/router.py`
- [ ] T066 [P] [US3] Knowledge list page with create dialog and empty state in `apps/web/src/routes/knowledge/KnowledgeListPage.tsx`
- [ ] T067 [P] [US3] Upload dialog: client size and type checks with the spec messages, Web Crypto SHA-256, check-duplicate verdict handling, Replace option, progress bar, in `apps/web/src/routes/knowledge/UploadDialog.tsx`
- [ ] T068 [US3] Knowledge base page: documents table with status polling, failure reason and retry, preview via signed URL, delete with confirm, KB delete listing agents, in `apps/web/src/routes/knowledge/KnowledgeBasePage.tsx`
- [ ] T097 [P] [US3] Add `display_name` (default `file_name`) to `kb_documents` in `services/api/app/migrations/versions/005_tools_knowledge.py`, accept it in the upload handler in `services/api/app/knowledge/service.py`, and cover it in `services/api/tests/contract/test_knowledge_contract.py`
- [ ] T098 [P] [US3] Upload dialog text with accepted types and 20 MB limit, optional display name, Upload disabled until a file is chosen, entry from the page header and the empty state, in `apps/web/src/routes/knowledge/UploadDialog.tsx` and `apps/web/src/routes/knowledge/KnowledgeListPage.tsx`

**Checkpoint**: Documents ingest and are manageable without any agent attached.

---

## Phase 6: User Story 4 - Retrieval during calls (Priority: P2)

**Goal**: Attach KBs to agents; `kb_search` system tool retrieves passages within p95 300 ms
(cap 800 ms); preview search on the KB page.

**Independent Test**: Quickstart section 4.

### Tests for User Story 4 (write first, must fail)

- [ ] T069 [US4] Extend `services/api/tests/contract/test_knowledge_contract.py` with `GET|PUT /v1/agents/{agent_id}/knowledge-bases` (10 limit, `knowledge_base_not_ready`), `POST /v1/knowledge-bases/{kb_id}/search`, `POST /v1/internal/knowledge/search` (service token, kb_ids must belong to the call's version)
- [ ] T070 [P] [US4] Retrieval quality test (SC-007: 50 labelled questions, correct passage in results for >= 85%) in `services/api/tests/integration/test_retrieval_quality.py` with `services/api/tests/fixtures/knowledge/qa_set.json`
- [ ] T071 [P] [US4] Integration test: deleting an attached KB detaches drafts and a published version referencing it gets empty results, in `services/api/tests/integration/test_knowledge_delete_detach.py`
- [ ] T072 [P] [US4] Worker kb_search tests (800 ms timeout returns empty with `timed_out`, "No relevant information" text, 4,000-character cap, event `kb` fields) in `services/voice-worker/tests/unit/test_kb_search.py`
- [ ] T073 [P] [US4] Latency benchmark for kb_search end to end (seeded 10,000-chunk workspace, recorded-latency embedding stub, 500 iterations; gates p95 <= 300 ms, max <= 800 ms) in `services/voice-worker/tests/harness/bench/bench_kb_search.py`, plus a nightly variant using the real embedding vendor
- [ ] T074 [P] [US4] Harness scenarios `kb_refund_question.yaml` and `kb_search_timeout.yaml` in `services/voice-worker/tests/harness/scenarios/`

### Implementation for User Story 4

- [ ] T075 [US4] Search in `services/api/app/knowledge/service.py`: Redis query-embedding cache (24 h), HNSW query with `hnsw.iterative_scan = relaxed_order` and `ef_search 40`, 0.30 threshold, top_k, 4,000-character cap, timings; attach-set validation
- [ ] T076 [US4] Endpoints `GET|PUT /v1/agents/{agent_id}/knowledge-bases`, `POST /v1/knowledge-bases/{kb_id}/search` (rate limited), `POST /v1/internal/knowledge/search` (workspace from call, kb_ids subset check) in `services/api/app/knowledge/router.py`
- [ ] T077 [US4] Capture `knowledge: [{kb_id, name, description}]` in the AgentVersion snapshot at publish via a `knowledge.service.describe_for_snapshot` call from `services/api/app/agent_versions/service.py` (coordinate with 002)
- [ ] T078 [US4] kb_search executor in `services/voice-worker/worker/tools/kb_search.py` (keep-alive client opened at session start, 800 ms timeout, numbered passages with source and page, event fields incl. cache hit)
- [ ] T079 [US4] Auto-inject `kb_search` in `services/voice-worker/worker/tools/registry.py` when the snapshot has KBs, description built from KB names and descriptions, and a `kb_search_enabled` switch the 004 flow executor can pass per node
- [ ] T080 [P] [US4] Agent knowledge picker grouped "Ready" and "Not ready" in `apps/web/src/routes/knowledge/components/AgentKnowledgePicker.tsx`, mounted in the agent edit page and flow global settings
- [ ] T081 [P] [US4] Search preview panel (query, results with file, page, heading, score) in `apps/web/src/routes/knowledge/SearchPreviewPanel.tsx`
- [ ] T099 [P] [US4] Attach dialog search, create-and-upload shortcut, empty-state text limited to PDF and DOCX, Confirm disabled while the selection equals the attached set, with tests, in `apps/web/src/routes/knowledge/components/AgentKnowledgePicker.tsx` and `apps/web/src/routes/knowledge/components/AgentKnowledgePicker.test.tsx`

**Checkpoint**: Agents answer from attached knowledge within the latency budget.

---

## Phase 7: User Story 5 - Tools in simulations (Priority: P3)

**Goal**: Canned responses per tool, simulation-mode execution, coverage check.

**Independent Test**: Quickstart section 5.

### Tests for User Story 5 (write first, must fail)

- [ ] T082 [US5] Extend `services/api/tests/contract/test_tools_contract.py` with `GET /v1/agents/{agent_id}/tools/mock-coverage`
- [ ] T083 [P] [US5] Worker tests for simulation mode (http returns mock without network, mapping applies, empty mock gives `no_mock_response`, transfer and press digit succeed without telephony, `mocked: true`) in `services/voice-worker/tests/unit/test_tool_mocks.py`
- [ ] T084 [P] [US5] Harness scenario `tools_http_simulated.yaml` asserting zero stub hits in `services/voice-worker/tests/harness/scenarios/`

### Implementation for User Story 5

- [ ] T085 [US5] `mock_coverage(agent_id)` in `services/api/app/tools/service.py`, including flow webhook nodes through an optional `flows.service.webhook_nodes_without_mock` hook (004)
- [ ] T086 [US5] Mock-coverage endpoint in `services/api/app/tools/router.py`
- [ ] T087 [US5] Simulation wrappers driven by `ToolContext.simulation` in `services/voice-worker/worker/tools/registry.py`
- [ ] T088 [P] [US5] Canned response field in `apps/web/src/routes/agents/tools/ToolEditorDialog.tsx` and a "missing mock" badge in `apps/web/src/routes/agents/tools/ToolsTab.tsx`
- [ ] T100 [US5] Canned response limited to http tools: CHECK constraint in `services/api/app/migrations/versions/005_tools_knowledge.py`, coverage listing only http tools and webhook nodes in `services/api/app/tools/service.py`, fixed simulated outcomes for end_call, transfer_call and press_digit in `services/voice-worker/worker/tools/registry.py`, field hidden for other types in `apps/web/src/routes/agents/tools/ToolEditorDialog.tsx`; tests in `services/voice-worker/tests/unit/test_tool_mocks.py`

---

## Phase 8: Polish and Cross-Cutting

- [ ] T089 [P] OpenTelemetry spans `tool.execute`, `kb.search`, `kb.ingest` with `call_id`, `tool_type` and timing attributes in `services/voice-worker/worker/tools/registry.py`, `services/api/app/knowledge/service.py` and `services/api/app/knowledge/jobs.py`
- [ ] T090 [P] Secret leak scan (SC-005): run the US1 to US5 suites with a canary secret and assert it never appears in API responses, call events, transcripts, snapshots or captured logs, in `services/api/tests/integration/test_secret_leak_scan.py`
- [ ] T091 Benchmark call set with and without tools and KBs attached (gate: no p50/p95 turn-latency regression > 5% against `baseline.json`) in `services/voice-worker/tests/harness/bench/bench_call_set_tools.py`; add T021, T041, T073 and T091 to the CI offline-harness job
- [ ] T092 Run quickstart.md end to end and record results in the PR description

---

## Dependencies and Execution Order

- Setup (T001 to T005) then Foundational (T006 to T015) block every story.
- US1 and US2 (both P1) can run in parallel after Phase 2; US2's T042 extends the service file
  from T023, so sequence those two tasks.
- US3 depends only on Phase 2. US4 depends on US3 (documents and chunks exist).
- US5 depends on US1 and US2 (tool types exist) and uses 008's simulation flag; it can ship
  before 008 because the harness sets the flag directly.
- Cross-feature: T025 and T077 touch 002's `agent_versions` publish path; T079's per-node switch
  and T085's webhook hook are consumed by 004.

### Within each story

Contract and unit tests first and failing, then models, services, routers, worker executors,
web. Benchmarks are written with the tests and must pass before the story is merged.

## Parallel Example: User Story 3

```text
T052 contract tests | T053 extract tests | T054 chunking tests | T055 charge tests | T056 ingestion integration
then
T057 models | T058 schemas | T059 storage | T060 extract | T061 chunking | T062 embeddings
then T063 service, T064 job, T065 router; web T066 and T067 in parallel, then T068
```

## Implementation Strategy

1. MVP: Phases 1 and 2, then US1 (end call and transfer make phone agents usable).
2. Add US2 (HTTP tools) for integrations; demo with quickstart section 2.
3. Add US3 then US4 for knowledge; ship once T073 passes its gate.
4. Add US5 when 008 simulations start.

## Notes

- Total 100 tasks: Setup 5, Foundational 10, US1 21, US2 19, US3 19, US4 14, US5 8, Polish 4.
  T093 to T100 come from the live UI walkthrough (research/ui-walkthrough/DELTA-resolution-004-006.md).
- Hot-path benchmarks: T021 (tool dispatch), T041 (HTTP tool), T073 (kb_search), T091 (call set).
