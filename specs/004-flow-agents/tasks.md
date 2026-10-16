---

description: "Task list for 004-flow-agents"
---

# Tasks: Flow Agents

**Input**: Design documents from `/specs/004-flow-agents/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/flows.yaml, quickstart.md

**Tests**: Required. Principle VII makes contract tests mandatory before implementation, and the
validator, compiler and executor are written test-first. Principle II requires latency
benchmarks for the executor (User Story 3).

**Organization**: Grouped by user story. Paths follow research/architecture.md section 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US5 from spec.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Module skeletons and dependencies

- [ ] T001 Create the flows API module skeleton (`__init__.py`, empty `router.py`, `schemas.py`, `models.py`, `service.py`) in services/api/app/flows/ and mount the router under `/v1` in services/api/app/main.py
- [ ] T002 [P] Add `@xyflow/react@12` and `@dagrejs/dagre@1` to apps/web/package.json
- [ ] T003 [P] Create the worker package skeleton services/voice-worker/worker/flow/__init__.py and services/voice-worker/worker/flow/nodes/__init__.py
- [ ] T004 [P] Add specs/004-flow-agents/contracts/flows.yaml to the assembly in contracts/openapi.yaml and regenerate the TypeScript client in apps/web/src/api/

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Table, schemas and shared helpers every story needs

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Write migration services/api/app/migrations/versions/004_flows.py: `flows` table per data-model section 1, RLS policy on `workspace_id`, unique `(agent_id)`, and partial index `call_events (call_id, seq) WHERE kind LIKE 'flow_%'`
- [ ] T006 [P] Write RLS isolation test (workspace A cannot read or write workspace B's flow) in services/api/tests/integration/flows/test_flows_rls.py
- [ ] T007 [P] Implement the `Flow` ORM model in services/api/app/flows/models.py
- [ ] T008 [P] Implement Pydantic schemas (FlowGraph, Node, the nine node configs, Overrides, Edge, Trigger, ValidationIssue, CompiledFlow, Operation, request and response models) in services/api/app/flows/schemas.py, importing `HttpRequestSpec` and `TransferSpec` from services/api/app/tools/schemas.py (005)
- [ ] T009 [P] Write unit tests for `{{var}}` parsing and the built-in variable list in services/api/tests/unit/flows/test_variables.py
- [ ] T010 Implement variable parsing and the built-in list in services/api/app/flows/variables.py (makes T009 pass)

**Checkpoint**: Foundation ready; user stories can start

---

## Phase 3: User Story 1 - Create a flow agent and design its graph (Priority: P1) MVP

**Goal**: Create a flow agent from name and language, edit the graph on a canvas, save drafts
safely.

**Independent Test**: quickstart.md sections 1 and 2.

### Tests for User Story 1 (write first, must fail)

- [ ] T011 [P] [US1] Contract tests for `POST /flows`, `GET /flows/{flow_id}`, `PUT /flows/{flow_id}`, `GET /agents/{agent_id}/flow` in services/api/tests/contract/test_flows_contract.py
- [ ] T012 [P] [US1] Unit test that the starter graph has start, agent, end, two edges and zero validation errors in services/api/tests/unit/flows/test_starter.py
- [ ] T013 [P] [US1] Integration test for atomic agent plus flow creation, language-seeded STT and TTS, empty-name rejection and unknown-language fallback warning in services/api/tests/integration/flows/test_create_flow_agent.py
- [ ] T014 [P] [US1] Integration test for `If-Match` handling (200 then 412 with `current_revision`, draft with errors still saved) with fixture services/api/tests/integration/flows/fixtures/clinic_v2.json in services/api/tests/integration/flows/test_save_revision.py
- [ ] T015 [P] [US1] Vitest test that dagre layout of a 100-node fixture has no overlaps and runs under 1 s in apps/web/src/routes/flows/canvas/layout.test.ts

### Implementation for User Story 1

- [ ] T016 [P] [US1] Implement the starter graph builder in services/api/app/flows/starter.py
- [ ] T017 [US1] Implement `create_flow_agent` (calls 002 `agents.service.create_agent` with type `flow` and language defaults, inserts flow, one transaction) in services/api/app/flows/service.py
- [ ] T018 [US1] Implement `get_flow`, `get_flow_by_agent` and `save_flow` with revision check and limit enforcement in services/api/app/flows/service.py
- [ ] T019 [US1] Implement the four US1 endpoints with `ETag` and `If-Match` handling and problem+json errors in services/api/app/flows/router.py
- [ ] T020 [P] [US1] Build the name and language form page in apps/web/src/routes/flows/NewFlowAgentPage.tsx
- [ ] T021 [P] [US1] Implement `useFlow` (load, save with ETag, conflict surfacing) in apps/web/src/routes/flows/hooks/useFlow.ts
- [ ] T022 [P] [US1] Implement dagre auto-layout and fit-to-screen helper in apps/web/src/routes/flows/canvas/layout.ts (makes T015 pass)
- [ ] T023 [P] [US1] Implement undo and redo (50 steps) in apps/web/src/routes/flows/canvas/useUndoRedo.ts
- [ ] T024 [P] [US1] Implement the nine node components with trigger-specific handles in apps/web/src/routes/flows/canvas/nodes/ (StartNode.tsx, AgentNode.tsx, TaskNode.tsx, ConditionNode.tsx, SayNode.tsx, ExtractNode.tsx, WebhookNode.tsx, TransferNode.tsx, EndNode.tsx)
- [ ] T025 [P] [US1] Implement the transition edge with label and condition badge in apps/web/src/routes/flows/canvas/edges/TransitionEdge.tsx
- [ ] T026 [P] [US1] Implement the drag palette with default labels and configs in apps/web/src/routes/flows/canvas/Palette.tsx
- [ ] T027 [US1] Implement the canvas (connect, select, multi-select, delete, duplicate, pan, zoom) in apps/web/src/routes/flows/canvas/FlowCanvas.tsx
- [ ] T028 [P] [US1] Implement node settings forms, one per type, in apps/web/src/routes/flows/panels/node-forms/ and the container apps/web/src/routes/flows/panels/NodePanel.tsx (webhook and transfer forms reuse 005 form components)
- [ ] T029 [P] [US1] Implement the edge panel with trigger-aware fields and the "how the agent sees this" preview in apps/web/src/routes/flows/panels/EdgePanel.tsx
- [ ] T030 [US1] Implement the builder page (toolbar, save, leave guard, reload-on-conflict dialog) in apps/web/src/routes/flows/FlowBuilderPage.tsx
- [ ] T031 [US1] Register `/agents/new/flow` and `/agents/:agentId/flow` in apps/web/src/app/router.tsx and route the agent-type chooser's Flow option to `/agents/new/flow`
- [ ] T100 [P] [US1] Vitest tests for Delete and Backspace deleting the selection (ignored while typing in a field), one undo step with an Undo notice, and toolbar controls having accessible names and tooltips in apps/web/src/routes/flows/canvas/FlowCanvas.test.tsx
- [ ] T101 [US1] Implement the canvas toolbar (Auto-layout, Fit to screen, zoom in, zoom out, tooltips) in apps/web/src/routes/flows/canvas/CanvasToolbar.tsx and keyboard delete with the Undo notice in apps/web/src/routes/flows/canvas/FlowCanvas.tsx (makes T100 pass)
- [ ] T102 [P] [US1] Integration test for `PUT /flows/{flow_id}` with `agent_settings`: graph and settings stored together or not at all, untouched settings unchanged, name renames the agent, 412 `agent_draft_changed`, 422 for `start_speaker` in changes, in services/api/tests/integration/flows/test_save_with_agent_settings.py
- [ ] T103 [US1] Implement `agent_settings` handling in `save_flow` (one transaction, deep merge through 002 `agents.service.update_draft` with expected revision, agent rename, `agent_draft_revision` in responses) in services/api/app/flows/service.py and services/api/app/flows/router.py (makes T102 pass)
- [ ] T104 [P] [US1] Field rules for node panels (ranges, E.164, absolute https URL, JSON parse errors with line) with tests in apps/web/src/routes/flows/panels/node-forms/fieldRules.ts and apps/web/src/routes/flows/panels/node-forms/fieldRules.test.ts
- [ ] T105 [P] [US1] Classify node with one handle per category, category picker and routing explanation on its connections, category rename carrying connections, inline category name errors, in apps/web/src/routes/flows/canvas/nodes/ConditionNode.tsx and apps/web/src/routes/flows/panels/EdgePanel.tsx
- [ ] T106 [P] [US1] Node card one-line summaries and the expanded multiline editor in apps/web/src/routes/flows/canvas/nodes/NodeSummary.tsx and apps/web/src/routes/flows/panels/node-forms/ExpandEditor.tsx
- [ ] T107 [P] [US1] Node form details: Start user-first optional greeting and generated-greeting note, Task field list or JSON Schema toggle, rule value hidden for `exists`, Extract name conversion with placeholder list, in apps/web/src/routes/flows/panels/node-forms/
- [ ] T108 [US1] Builder header (name bound to the agent name with inline empty check, copy agent ID, version chip opening 002 history, settings, Save, Publish), side panel switching between assistant/test tabs and selection settings, and save-before-test prompt, in apps/web/src/routes/flows/FlowBuilderPage.tsx

**Checkpoint**: A flow agent can be created, edited and saved; reload restores it exactly

---

## Phase 4: User Story 2 - Validate and publish a flow (Priority: P1)

**Goal**: Server-side validation, compile preview, publish into an immutable AgentVersion.

**Independent Test**: quickstart.md section 3.

### Tests for User Story 2 (write first, must fail)

- [ ] T032 [P] [US2] Contract tests for `POST /flows/{flow_id}/validate`, `/compile`, `/publish` in services/api/tests/contract/test_flows_publish_contract.py
- [ ] T033 [P] [US2] Unit tests with one failing and one passing graph per issue code in data-model section 3 in services/api/tests/unit/flows/test_validation.py
- [ ] T034 [P] [US2] Unit tests for transition name derivation, overrides and clash detection in services/api/tests/unit/flows/test_transitions.py
- [ ] T035 [P] [US2] Golden-file compiler tests (graph in, expected CompiledFlow out, stable `graph_hash`, hash unchanged by position or viewport edits) in services/api/tests/unit/flows/test_compiler.py with fixtures in services/api/tests/unit/flows/golden/
- [ ] T036 [P] [US2] Integration test that publish refuses graphs with errors (422 `flow_has_errors`), rejects stale `expected_revision` (409), and creates an AgentVersion with `config.flow.{graph, graph_hash, compiled}` in services/api/tests/integration/flows/test_publish.py

### Implementation for User Story 2

- [ ] T037 [P] [US2] Implement transition naming and descriptions in services/api/app/flows/transitions.py (makes T034 pass)
- [ ] T038 [US2] Implement the validator (adjacency, start rules, trigger table, BFS reachability, reverse BFS exits, def/use variables, tool and catalog references, limits, stable ordering) in services/api/app/flows/validation.py (makes T033 pass)
- [ ] T039 [US2] Implement the compiler and `graph_hash` canonicalisation in services/api/app/flows/compiler.py, resolving tools through 005 `tools.service.resolve_for_snapshot` (makes T035 pass)
- [ ] T040 [P] [US2] Add a schema export script services/api/app/flows/export_schema.py that writes services/voice-worker/worker/flow/compiled_schema.json, plus a CI check that the committed file is current
- [ ] T041 [US2] Implement `validate_graph`, `compile_preview`, `compile_draft` (used by 003 test sessions) and `publish` (calls 002 `agent_versions.service.create_version`) in services/api/app/flows/service.py; run validation on every save
- [ ] T042 [US2] Add the validate, compile and publish endpoints in services/api/app/flows/router.py (makes T032 and T036 pass)
- [ ] T043 [P] [US2] Implement debounced validation (600 ms) in apps/web/src/routes/flows/hooks/useValidate.ts
- [ ] T044 [P] [US2] Implement the problem list with click-to-select and inline remove for dangling edges in apps/web/src/routes/flows/panels/ValidationPanel.tsx
- [ ] T045 [P] [US2] Implement the publish dialog (release notes, warning count, error block) and compile preview view in apps/web/src/routes/flows/panels/PublishDialog.tsx and apps/web/src/routes/flows/panels/CompilePreview.tsx
- [ ] T109 [P] [US2] Validation and naming tests: `E_GREETING_SOURCE`, `E_INVALID_FIELD` (max rounds 0 and 25, number "12345", URL "notaurl", invalid JSON), `E_CATEGORY_NAME`, `E_TRANSITION_NAME_EMPTY`, no label needed on start, say and extract edges, and names for "Route To Billing!", "Route to billing" and "!!!" from shared vectors services/api/tests/unit/flows/fixtures/transition_names.json, in services/api/tests/unit/flows/test_validation.py and services/api/tests/unit/flows/test_transitions.py
- [ ] T110 [US2] Implement the four new codes in services/api/app/flows/validation.py, the no-double-prefix rule in services/api/app/flows/transitions.py, and the TypeScript preview copy in apps/web/src/routes/flows/panels/transitionName.ts checked against the same vectors (makes T109 pass)

**Checkpoint**: Valid flows publish into versions; invalid ones are blocked with precise issues

---

## Phase 5: User Story 3 - Callers move through the flow (Priority: P1)

**Goal**: The worker runs the compiled flow, records every move, and announces node entries.

**Independent Test**: quickstart.md section 4, plus the benchmarks in section 7.

### Tests for User Story 3 (write first, must fail)

- [ ] T046 [P] [US3] Contract test for `GET /calls/{call_id}/flow-transitions` (ordered items, empty for single-prompt agents, 404 across workspaces) in services/api/tests/contract/test_flow_transitions_contract.py
- [ ] T047 [P] [US3] Unit tests for the rule evaluator (every operator, numeric coercion, regex guard, else) in services/voice-worker/tests/unit/flow/test_rules.py
- [ ] T048 [P] [US3] Unit tests for `{{var}}` substitution and missing-variable reporting in services/voice-worker/tests/unit/flow/test_templating.py
- [ ] T049 [P] [US3] Unit tests for handler registration, unknown node type rejection and the 200-transition guard in services/voice-worker/tests/unit/flow/test_registry.py
- [ ] T050 [P] [US3] Harness scenarios services/voice-worker/tests/harness/scenarios/flow_triage_support.yaml, flow_rule_else.yaml, flow_task_max_rounds.yaml, flow_webhook_failure_branch.yaml, flow_transfer_web_call_fallback.yaml, flow_loop_guard.yaml with runner services/voice-worker/tests/harness/test_flow_scenarios.py asserting node paths, triggers and disconnect reasons
- [ ] T051 [P] [US3] Engine overhead benchmark with stubbed adapters (500 runs, p50 and p95 per move, fails above 150 ms p95) in services/voice-worker/tests/harness/bench/bench_flow_engine.py
- [ ] T052 [P] [US3] Turn-latency benchmark for flow agents on the default stack against the single-prompt baseline (fails above p50 800 ms, p95 1500 ms, or more than 5% regression on turns without a move) in services/voice-worker/tests/harness/bench/bench_flow_turn_latency.py

### Implementation for User Story 3

- [ ] T053 [P] [US3] Implement the safe rule evaluator in services/voice-worker/worker/flow/rules.py (makes T047 pass)
- [ ] T054 [P] [US3] Implement templating in services/voice-worker/worker/flow/templating.py (makes T048 pass)
- [ ] T055 [P] [US3] Implement the `NodeHandler` protocol and registry in services/voice-worker/worker/flow/registry.py
- [ ] T056 [P] [US3] Implement CallEvent posting (`flow_node_entered`, `flow_transition`, `flow_task_completed`, `flow_variables_set`) and data-channel announcements on topic `callwright.flow` in services/voice-worker/worker/flow/events.py
- [ ] T057 [US3] Implement `FlowExecutor` (load compiled flow, run state, transition guard, first-transition-wins rule, timing for `engine_ms`) in services/voice-worker/worker/flow/executor.py (makes T049 pass)
- [ ] T058 [P] [US3] Implement the start handler (who speaks first, static or generated greeting) in services/voice-worker/worker/flow/nodes/start.py
- [ ] T059 [US3] Implement conversational handlers for agent and task nodes (per-node Agent instance, parameterless transition tools, entry line spoken on handoff, `complete_task` function, max-rounds forced completion, `inherit` context) in services/voice-worker/worker/flow/nodes/conversational.py
- [ ] T060 [P] [US3] Implement condition handler (classify with enum structured output, 1500 ms timeout and `fallback`; rule via rules.py) in services/voice-worker/worker/flow/nodes/condition.py
- [ ] T061 [P] [US3] Implement say handler (interruptible or not) in services/voice-worker/worker/flow/nodes/say.py
- [ ] T062 [P] [US3] Implement extract handler (one silent structured-output pass, store variables) in services/voice-worker/worker/flow/nodes/extract.py
- [ ] T063 [P] [US3] Implement webhook handler over 005 services/voice-worker/worker/tools/http.py (mappings to variables, success and failure targets, mock response in simulations) in services/voice-worker/worker/flow/nodes/webhook.py
- [ ] T064 [P] [US3] Implement transfer handler over 005 services/voice-worker/worker/tools/transfer.py (failure target, web-call fallback) in services/voice-worker/worker/flow/nodes/transfer.py
- [ ] T065 [P] [US3] Implement end handler over 005 services/voice-worker/worker/tools/end_call.py (message, reason stored, disconnect `agent_hangup`) in services/voice-worker/worker/flow/nodes/end.py
- [ ] T066 [US3] Delegate to `FlowExecutor` when `config.type == "flow"` in services/voice-worker/worker/pipeline.py (003-owned file; minimal change reviewed with 003 owners)
- [ ] T067 [US3] Add `engine_ms` and `transition_llm_ms` per-turn meters in services/voice-worker/worker/metrics.py
- [ ] T068 [US3] Implement the transitions read projection in services/api/app/flows/service.py and endpoint `GET /calls/{call_id}/flow-transitions` in services/api/app/flows/router.py (makes T046 pass)
- [ ] T069 [P] [US3] Implement the data-channel listener that pulses the active node in apps/web/src/routes/flows/hooks/useFlowEvents.ts
- [ ] T070 [P] [US3] Implement the Test tab (starts a 003 web test session with `use_draft: true`, blocks when the draft has errors) in apps/web/src/routes/flows/test/FlowTestPanel.tsx
- [ ] T071 [P] [US3] Implement the per-call node path timeline for 006's call detail in apps/web/src/routes/calls/components/FlowPathTimeline.tsx
- [ ] T072 [US3] Run T050 to T052, record baseline results in services/voice-worker/tests/harness/bench/results/, and add the benchmark gate to CI for changes under services/voice-worker/worker/flow/

**Checkpoint**: A published flow runs end to end in the harness; moves are recorded and visible

---

## Phase 6: User Story 4 - Tune nodes and flow-wide defaults (Priority: P2)

**Goal**: Per-node overrides, context strategies, node tools and knowledge search, global
settings drawer.

**Independent Test**: quickstart.md section 5.

### Tests for User Story 4 (write first, must fail)

- [ ] T073 [P] [US4] Compiler tests for override resolution, "use agent default" following the agent config, node-only tools, flow-level tools on every conversational node, and `kb_search_enabled` in services/api/tests/unit/flows/test_compiler_overrides.py
- [ ] T074 [P] [US4] Validation tests for `E_UNKNOWN_CATALOG` and `E_UNKNOWN_TOOL` against stubbed 002 catalogs and 005 tool library in services/api/tests/unit/flows/test_validation_references.py
- [ ] T075 [P] [US4] Unit tests for `summarize` (background summary used, last-6-turns fallback, never awaited on handoff) and `reset` in services/voice-worker/tests/unit/flow/test_context.py
- [ ] T076 [P] [US4] Harness scenario services/voice-worker/tests/harness/scenarios/flow_overrides_context.yaml asserting per-node model, language, tool set and context isolation

### Implementation for User Story 4

- [ ] T077 [US4] Resolve overrides against 002 catalogs and agent defaults, merge flow-level and node tools, and emit `kb_search` blocks in services/api/app/flows/compiler.py (makes T073 pass)
- [ ] T078 [US4] Add catalog and tool reference checks in services/api/app/flows/validation.py (makes T074 pass)
- [ ] T079 [US4] Implement `inherit`, `summarize` (background summarizer task) and `reset` in services/voice-worker/worker/flow/context.py and use it from services/voice-worker/worker/flow/nodes/conversational.py (makes T075 pass)
- [ ] T080 [US4] Build per-node `llm`, `tts`, `stt` through 003 adapter factories and inject 005 kb_search only when enabled in services/voice-worker/worker/flow/nodes/conversational.py
- [ ] T081 [P] [US4] Implement the overrides section (each field with "use agent default", temperature and stability presets) in apps/web/src/routes/flows/panels/node-forms/OverridesSection.tsx
- [ ] T082 [P] [US4] Implement the node tool picker over the 005 tool library in apps/web/src/routes/flows/panels/node-forms/ToolPicker.tsx
- [ ] T083 [P] [US4] Implement the global settings drawer (`?configure=<tab>`; model, voice, call behaviour, tools, knowledge, quality checks and persona prompt, reusing 002, 005 and 007 forms) in apps/web/src/routes/flows/panels/GlobalSettingsDrawer.tsx
- [ ] T111 [P] [US4] Global settings modal: seven deep-linked sections, save-mode label per section with unsaved markers, ring duration in Call behaviour, who speaks first bound to the Start node, Advanced including 007's analysis variables form, draft sections collected into `agent_settings` for Save, in apps/web/src/routes/flows/panels/GlobalSettingsDrawer.tsx
- [ ] T112 [P] [US4] Tool picker empty state with a create-tool shortcut in apps/web/src/routes/flows/panels/node-forms/ToolPicker.tsx; override rules (provider change clears voice and model, fixed-temperature display, language override) in apps/web/src/routes/flows/panels/node-forms/OverridesSection.tsx

**Checkpoint**: Node overrides and context strategies verified in the harness

---

## Phase 7: User Story 5 - Build or change a flow with the AI assistant (Priority: P3)

**Goal**: Assistant proposals shown as a diff, applied only on approval, charged per request.

**Independent Test**: quickstart.md section 6.

### Tests for User Story 5 (write first, must fail)

- [ ] T084 [P] [US5] Contract test for `POST /flows/{flow_id}/assistant` (200, 402, 409, 504 shapes) in services/api/tests/contract/test_flows_assistant_contract.py
- [ ] T085 [P] [US5] Unit tests for temp-id remapping, operation application (remove_node cascades to edges, update_node deep merge), rejection of operations on unknown ids, and absence of overrides in services/api/tests/unit/flows/test_assistant_ops.py
- [ ] T086 [P] [US5] Integration test with a stubbed LLM adapter: proposal validated, `billing.charge_feature` called once with `flow_assistant`, nothing charged on timeout, stale `base_revision` gives 409, in services/api/tests/integration/flows/test_assistant.py
- [ ] T087 [P] [US5] Vitest test that Decline restores the exact pre-proposal graph and Approve is one undo step in apps/web/src/routes/flows/assistant/ProposalBar.test.tsx

### Implementation for User Story 5

- [ ] T088 [US5] Implement the assistant (system prompt, JSON-schema response without overrides, LLM adapter call with 60 s timeout, id remap, apply, validate, charge) in services/api/app/flows/assistant.py (makes T085 and T086 pass)
- [ ] T089 [US5] Add the assistant endpoint in services/api/app/flows/router.py (makes T084 pass)
- [ ] T090 [P] [US5] Implement diff styling for added, removed and updated nodes and edges in apps/web/src/routes/flows/canvas/diffOverlay.ts
- [ ] T091 [P] [US5] Implement the assistant chat panel (session-only history, retry on timeout) in apps/web/src/routes/flows/assistant/AssistantPanel.tsx
- [ ] T092 [US5] Implement the pending-changes bar with Approve and Decline, canvas lock while pending, and issue list in apps/web/src/routes/flows/assistant/ProposalBar.tsx (makes T087 pass)
- [ ] T113 [US5] Place assistant-added nodes next to their neighbours without overlap and without moving existing nodes (data-model section 7) in services/api/app/flows/assistant.py, with cases in services/api/tests/unit/flows/test_assistant_ops.py

**Checkpoint**: All five stories independently functional

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T093 [P] Add OpenTelemetry spans `flow.transition` and `flow.node` with `call_id`, `node_id` attributes in services/voice-worker/worker/flow/executor.py and `flows.publish`, `flows.assistant` spans in services/api/app/flows/service.py
- [ ] T094 [P] Playwright end-to-end test (create flow agent, add nodes, fix a validation error, publish) in apps/web/e2e/flow_build_publish.spec.ts
- [ ] T095 [P] Load test for save and validate (p95 under 300 ms at 200 nodes) in services/api/tests/integration/flows/test_flow_save_perf.py
- [ ] T096 Security review: confirm webhook node secrets never appear unmasked in `GET /flows/{flow_id}`, compile preview or published versions, with a test in services/api/tests/integration/flows/test_flow_secrets_masked.py
- [ ] T097 [P] Implement `flows.service.webhook_nodes_without_mock(workspace_id, agent_id)` for 005's `GET /v1/agents/{agent_id}/tools/mock-coverage`, with a unit test in services/api/tests/unit/flows/test_cross_feature_hooks.py, in services/api/app/flows/service.py
- [ ] T098 Implement `flows.service.tool_node_usages(workspace_id, tool_id)` returning `{agent_id, flow_id, node_ids}` for 005's `GET /v1/tools/{tool_id}/usages` (`flow_node_ids`), tested in services/api/tests/unit/flows/test_cross_feature_hooks.py, in services/api/app/flows/service.py
- [ ] T099 Run every quickstart.md scenario and record results in specs/004-flow-agents/quickstart.md

---

## Cross-spec additions (architecture v1.2)

- [ ] T114 Node overrides (model, voice temperature, speed, volume, STT) validate and clamp through 002's `agents.service.validate_override()` and shared range table; node panel sliders read their ranges from the same table (no 0 to 1 control mapped onto a 0 to 2 field) in `services/api/app/flows/service.py` and `apps/web/src/routes/flows/panels/`; contract test in `services/api/tests/contract/test_flows_contract.py`

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after Setup; blocks all stories. T008 needs 005's
  `tools/schemas.py` (`HttpRequestSpec`, `TransferSpec`); if 005 has not landed, add a temporary
  local stub with the same field names and replace it when 005 merges.
- **US1 (Phase 3)**: after Phase 2
- **US2 (Phase 4)**: after Phase 2; publish needs US1's `save_flow` (T018)
- **US3 (Phase 5)**: needs US2's compiler and schema export (T039, T040). Webhook, transfer and
  end handlers (T063 to T065) need 005's worker tool executors. T066 needs 003's pipeline.
- **US4 (Phase 6)**: after US3 (extends compiler and conversational handler)
- **US5 (Phase 7)**: after US2 (uses validator); independent of US3 and US4
- **Polish (Phase 8)**: after the stories in scope

### External Dependencies

- 002: `agents.service.create_agent`, language defaults, catalogs, `agent_versions.service.create_version`
- 003: `pipeline.py`, adapter factories, `/v1/internal/calls/{id}/events`, `call_events`, test sessions with `use_draft`
- 005: `tools/schemas.py`, `tools.service.resolve_for_snapshot`, `worker/tools/{http,transfer,end_call,kb_search}.py`
- 001: `billing.charge_feature`, RLS session

### Within Each User Story

- Contract and unit tests first, failing, then models, services, endpoints, UI
- Validator and compiler before anything that publishes; executor core before node handlers

## Parallel Example: User Story 3

```bash
# Tests together:
Task: "T046 contract test flow-transitions in services/api/tests/contract/test_flow_transitions_contract.py"
Task: "T047 rule evaluator tests in services/voice-worker/tests/unit/flow/test_rules.py"
Task: "T050 harness scenarios in services/voice-worker/tests/harness/scenarios/"
Task: "T051 engine benchmark in services/voice-worker/tests/harness/bench/bench_flow_engine.py"

# Node handlers together once T055 and T057 are done:
Task: "T060 condition.py"  Task: "T061 say.py"  Task: "T062 extract.py"  Task: "T063 webhook.py"
```

## Implementation Strategy

### MVP

US1 + US2 + US3 with agent, say, condition and end nodes is the smallest version that takes a
real call. Task, extract, webhook and transfer handlers complete US3 once 005's executors exist.

### Incremental Delivery

1. Phases 1 and 2
2. US1: build and save (demo the canvas)
3. US2: validate and publish (versions contain compiled flows)
4. US3: calls run flows; benchmarks gate merge
5. US4: overrides and context strategies
6. US5: assistant

### Notes

- Task count: 113 (Setup 4, Foundational 6, US1 30, US2 16, US3 27, US4 13, US5 10, Polish 7).
  T100 to T113 come from the live UI walkthrough (research/ui-walkthrough/DELTA-resolution-004-006.md)
- T066 edits a 003-owned file; coordinate the change with the 003 owners
