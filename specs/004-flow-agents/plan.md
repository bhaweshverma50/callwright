# Implementation Plan: Flow Agents

**Branch**: `004-flow-agents` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-flow-agents/spec.md`

## Summary

Operators build branching voice agents on a canvas of nine node types. The API stores one graph
document per flow agent with revision-checked saves, validates it with a single server-side rule
set, and on publish compiles it into a self-contained `compiled_flow` that is embedded in a new
immutable AgentVersion (002). The voice worker gains a flow executor in
`services/voice-worker/worker/flow/` that runs the compiled graph as a state machine on the
LiveKit Agents handoff pattern, records every node move as a CallEvent, and announces node entries
on the data channel for live canvas highlighting. An AI assistant returns validated, id-remapped
operations that the client shows as a diff and applies only on approval.

## Technical Context

**Language/Version**: Python 3.12 (API, worker); TypeScript 5.x (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq (not used by this
feature), LiveKit Agents (Python) 1.x; React 18, Vite, TanStack Query, React Router,
`@xyflow/react` 12, `@dagrejs/dagre` 1.x, Tailwind with Radix primitives, `livekit-client`
**Storage**: PostgreSQL 16 (`flows` table, JSONB graph; reads 003's `call_events`)
**Testing**: pytest (unit, contract via schemathesis-style OpenAPI checks, integration),
voice-worker offline harness (`services/voice-worker/tests/harness/`), Vitest + Testing Library
for the canvas, Playwright for one end-to-end build-and-publish path
**Target Platform**: Linux containers (API, worker); evergreen browsers (web)
**Project Type**: Web application (SPA + API + voice worker)
**Performance Goals**: validate 200-node graph under 20 ms server time; save p95 under 300 ms;
auto-layout of 100 nodes under 1 s in the browser; executor overhead per node move p95 at most
150 ms excluding model time; node highlight under 1 s after the move
**Constraints**: platform turn latency p50 at most 800 ms and p95 at most 1500 ms must hold for
flow agents (Principle II); worker reads only the compiled snapshot (Principle I); no vendor
named in executor code
**Scale/Scope**: up to 200 nodes and 500 edges per flow; one flow per agent; thousands of flows
per deployment

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design: still passing.*

| Principle | Gate | Status |
|---|---|---|
| I. Provider-agnostic pipeline | Per-node `llm`, `tts`, `stt` overrides are plain config resolved at compile time and instantiated through 003's adapter factories; executor and node handlers import no vendor SDK. The assistant model is a catalog entry (`FLOW_ASSISTANT_MODEL`), not hard-coded. | Pass |
| II. Latency is a feature | Hot-path impact stated in research R10 to R13: parameterless transition tools, entry lines spoken on handoff, background summaries, classify capped at 1500 ms. Benchmarks for executor overhead and full-turn latency on flow agents are tasks in User Story 3 and must pass before merge. Per-turn metrics add `transition_llm_ms` and `engine_ms`. | Pass |
| III. Metered and auditable | Flow calls are priced like any call (all model tokens, including classify, extract and background summaries, are LLM usage meters on the call). Assistant requests go through `billing.charge_feature(..., "flow_assistant", ...)`. | Pass |
| IV. Quality measured | Every call stores its node path (`flow_transition` events) so 007 can attribute verdicts per node and 008 can compare original and simulated paths. Versions embed graph plus `graph_hash` so evaluator results map to the exact flow. | Pass |
| V. Tenancy and privacy | `flows` has RLS on `workspace_id`; the transitions read endpoint goes through RLS on `call_events`. Webhook node secrets are stored by 005's secrets mechanism and appear in graphs and compiled configs only as references, masked in API responses. Assistant prompts include only the workspace's own graph. | Pass |
| VI. Simplicity | No new service, queue or table beyond `flows`. Graph is one JSONB document. Transitions reuse `call_events`. Validation exists once (server). | Pass |
| VII. Contracts and money | `contracts/flows.yaml` has contract tests that run before implementation. Compiler and validator are test-first with golden graphs. The executor is covered by offline harness scenarios. Assistant charging has a unit test against `billing.charge_feature`. | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/004-flow-agents/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── flows.yaml
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/flows/
├── router.py            /v1/flows*, /v1/agents/{agent_id}/flow, /v1/calls/{call_id}/flow-transitions
├── schemas.py           FlowGraph, Node configs, Edge, ValidationIssue, CompiledFlow, Operation
├── models.py            Flow ORM model
├── service.py           create (agent + flow), get, save (revision check), publish, compile_draft
├── validation.py        rule set from data-model section 3
├── compiler.py          graph to CompiledFlow, graph_hash
├── variables.py         def/use analysis, built-in variable list
├── transitions.py       function-name derivation, descriptions
├── assistant.py         prompt, LLM call, id remap, apply operations, validate
└── starter.py           starter graph for new flow agents
services/api/app/migrations/versions/004_flows.py
services/api/tests/
├── contract/test_flows_contract.py
├── unit/flows/          test_validation.py, test_compiler.py, test_transitions.py,
│                        test_variables.py, test_assistant_ops.py, test_starter.py
├── unit/flows/golden/   golden graphs and expected compiled output
└── integration/flows/   test_create_flow_agent.py, test_save_revision.py, test_publish.py,
                         test_flow_transitions_read.py, test_assistant.py

services/voice-worker/worker/flow/
├── executor.py          FlowExecutor state machine, transition guard
├── registry.py          NodeHandler protocol and registry (extension point)
├── nodes/               start.py, conversational.py (agent, task), condition.py, say.py,
│                        extract.py, webhook.py, transfer.py, end.py
├── context.py           inherit / summarize / reset, background summarizer
├── rules.py             safe rule evaluator
├── templating.py        {{var}} substitution
├── events.py            CallEvent posting and data-channel announcements
└── compiled_schema.json exported from the API, checked in CI
services/voice-worker/tests/
├── unit/flow/           test_rules.py, test_context.py, test_registry.py, test_templating.py
├── harness/scenarios/flow_*.yaml   scripted callers for flow agents
└── harness/bench/       bench_flow_engine.py, bench_flow_turn_latency.py

apps/web/src/routes/flows/
├── NewFlowAgentPage.tsx          /agents/new/flow
├── FlowBuilderPage.tsx           /agents/:id/flow
├── canvas/                       FlowCanvas.tsx, nodes/<Type>Node.tsx, edges/TransitionEdge.tsx,
│                                 Palette.tsx, layout.ts (dagre), useUndoRedo.ts, diffOverlay.ts
├── panels/                       NodePanel.tsx, node-forms/<Type>Form.tsx, EdgePanel.tsx,
│                                 ValidationPanel.tsx, GlobalSettingsDrawer.tsx, PublishDialog.tsx
├── assistant/                    AssistantPanel.tsx, ProposalBar.tsx
├── test/                         FlowTestPanel.tsx (uses 003 test session, data-channel listener)
└── hooks/                        useFlow.ts, useValidate.ts, useFlowEvents.ts
apps/web/src/routes/calls/components/FlowPathTimeline.tsx   (consumed by 006 call detail)
apps/web/src/api/                 regenerated client from contracts/openapi.yaml
```

**Structure Decision**: Follows architecture section 2 exactly: API module `flows`, worker package
`worker/flow/`, web area `routes/flows/`. The call-detail timeline component is placed under
`routes/calls/components/` so 006 can mount it without depending on the builder.

## Key Design Points

1. **Create**: `POST /v1/flows {name, language}` creates the agent (002 service call) and the flow
   with the starter graph in one transaction (research R15).
2. **Save**: `PUT /v1/flows/{flow_id}` with `If-Match` revision; body is the full graph plus name;
   response returns the new revision and the validation result. Drafts with errors are saved.
3. **Validate**: `POST /v1/flows/{flow_id}/validate` accepts an unsaved graph; same code path as
   save and publish.
4. **Compile preview**: `POST /v1/flows/{flow_id}/compile` returns `compiled` or issues, no write.
5. **Publish**: `POST /v1/flows/{flow_id}/publish {release_notes, expected_revision}` validates,
   compiles, then calls 002 `agent_versions.service.create_version` with `config.flow` (data model
   section 5). Returns the new `agv_` id and warning count.
6. **Global settings**: the drawer edits the agent through 002's agent endpoints (model, voice,
   STT, call behaviour, tools via 005, knowledge bases via 005, quality checks via 007); only the
   graph and flow name are stored by this module. The persona prompt is the agent's `prompt`.
7. **Runtime**: 003's `pipeline.py` checks `config.type`; for `flow` it builds
   `FlowExecutor(config.flow.compiled, session, adapters, tools_runtime, events)`. Handlers for
   webhook, transfer and end call 005's `worker/tools/http.py`, `transfer.py`, `end_call.py`.
8. **Transitions read**: `GET /v1/calls/{call_id}/flow-transitions` in the flows router.
9. **Assistant**: `POST /v1/flows/{flow_id}/assistant` (research R17), 60 s timeout, charged.

## Dependencies

- **002 agent-builder**: `agents.service.create_agent`, agent draft config, language-defaults
  catalog, LLM/voice/STT catalogs for override validation, `agent_versions.service.create_version`.
- **003 voice-runtime**: `pipeline.py` hook, adapter factories, `POST /v1/internal/calls/{id}/events`,
  `call_events` table, web test session with `use_draft`.
- **005 tools-knowledge**: `HttpRequestSpec`, `TransferSpec`, `tools.service.resolve_for_snapshot`,
  worker tool executors, kb_search injection. Webhook, transfer and node-tool behaviour cannot be
  completed before 005 lands; the rest of this feature can. In return 004 provides two hooks to
  005: `flows.service.webhook_nodes_without_mock(workspace_id, agent_id)` (mock coverage) and
  `flows.service.tool_node_usages(workspace_id, tool_id)` (tool usages with node ids).
- **001**: `billing.charge_feature`, auth, RLS session.

## Complexity Tracking

No constitution violations. One deviation from architecture.md to note for review:

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| AgentConfig snapshot gains a `flow` block (graph, graph_hash, compiled) instead of only `flow_id` | Spec FR-028 requires the compiled form stored with the version; a bare `flow_id` would point at a mutable draft | Referencing the mutable `flows` row breaks version immutability (Principle I) |
| Benchmarks under `services/voice-worker/tests/harness/bench/` (path not listed in architecture section 2) | Principle II benchmark call set needs a home next to the harness it reuses | Putting benchmarks in unit tests would run them on every CI job and make them flaky |
