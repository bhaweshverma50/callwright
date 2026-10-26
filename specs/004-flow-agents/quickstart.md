# Quickstart: Flow Agents

**Feature**: 004-flow-agents | **Date**: 2026-10-16

Validation scenarios for reviewers and for the final task in tasks.md. Assumes the local stack
from 001 (API, Postgres with RLS, Redis, web dev server) and the voice worker harness from 003,
plus a signed-in test workspace with credit. `$TOKEN` is a workspace JWT; `$API` is
`http://localhost:8000/v1`.

## 1. Create a flow agent (US1)

```bash
curl -s -X POST $API/flows -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Clinic intake","language":"en-GB"}' | tee /tmp/flow.json
```

Expect `201`, an `agent_id` (`agt_...`), a `flow.id` (`flw_...`), `flow.revision` 1, a graph of
three nodes (start, agent, end) and two edges, and `last_validation.errors` 0. Fetch the agent
(002) and confirm its STT and TTS settings match the en-GB defaults.

In the browser: `/agents/new` then Flow, enter the same values, and confirm the canvas opens at
`/agents/<agent_id>/flow` with the three nodes connected.

## 2. Save with revision check (US1)

```bash
FLOW=$(jq -r .flow.id /tmp/flow.json)
curl -s -X PUT $API/flows/$FLOW -H "Authorization: Bearer $TOKEN" -H 'If-Match: "1"' \
  -H 'Content-Type: application/json' -d @services/api/tests/integration/flows/fixtures/clinic_v2.json
# repeat with If-Match "1": expect 412, code flow_revision_conflict, current_revision 2
```

Browser: open the flow in two tabs, save in tab A, then save in tab B. Tab B shows the reload
message. Auto-layout a deliberately messy graph and confirm no node overlaps; reload and confirm
positions persisted.

## 3. Validation and publish (US2)

1. Add a second Start node and an unconnected Say node. Validation panel shows `E_START_COUNT`
   (error) and `W_UNREACHABLE` (warning). Clicking each selects the node.
2. `POST $API/flows/$FLOW/publish` with `{"expected_revision": <rev>}` returns `422`
   `flow_has_errors` with the issues.
3. Remove the extra Start, publish again: `201` with `agent_version_id`, `warnings` 1.
4. Fetch the version (002 `GET /v1/agents/{agent_id}/versions/{version_id}`) and confirm
   `config.flow.graph`, `config.flow.graph_hash` and `config.flow.compiled.schema_version == 1`.
5. Move a node only and publish again: `graph_hash` is unchanged.

## 4. Runtime path (US3)

Offline harness, no telephony:

```bash
cd services/voice-worker
uv run pytest tests/harness/test_flow_scenarios.py -k flow_triage_support -q
```

Scenario `tests/harness/scenarios/flow_triage_support.yaml` publishes Start, Triage (agent),
Route (classify: Sales, Support), Support line (say), End, and a scripted caller asking for
support. Expected: node path start, triage, route, support_line, end; call ends with
`agent_hangup`; `GET $API/calls/<call_id>/flow-transitions` returns 4 items in order with
triggers `always`, `llm_condition`, `category`, `always`.

Browser: start a test call from the Test tab and confirm the active node pulses within 1 second
of each move.

Other harness scenarios to run: `flow_rule_else`, `flow_task_max_rounds`,
`flow_webhook_failure_branch`, `flow_transfer_web_call_fallback`, `flow_loop_guard`.

## 5. Overrides and context (US4)

Harness scenario `flow_overrides_context`: node A uses the default model, node B overrides model
and language (es) with `context_strategy: reset` and one node-only tool. Assert from recorded
CallEvents: per-turn `llm.model` differs between A and B, B's first model request contains no
caller turns from A, and the node-only tool is absent from A's tool list.

## 6. Assistant diff (US5)

Browser: on a 3-node flow, ask "add a step that collects date of birth before the end".
Expect the Pending changes bar, green added Task node, red struck-through removed edge, two green
edges, and the issue list. Decline: canvas identical (compare with the saved graph JSON). Ask
again, Approve, Save: the draft validates; the workspace usage report (001) shows a
`flow_assistant` line.

## 7. Latency benchmarks (Principle II)

```bash
cd services/voice-worker
uv run python -m tests.harness.bench.bench_flow_engine            # engine overhead, 500 runs
uv run python -m tests.harness.bench.bench_flow_turn_latency      # flow turns against single prompt
```

Pass criteria: engine overhead per move p95 at most 150 ms; flow agent turns on the default
stack p50 at most 800 ms and p95 at most 1500 ms, and no regression greater than 5% against the
single-prompt baseline on turns without a move. Results are written to
`services/voice-worker/tests/harness/bench/results/` and compared in CI.

## 8. Live walkthrough deltas (FR-040 to FR-058)

```bash
# Atomic save: graph plus a changed setting; a stale agent draft revision stores nothing
curl -s -X PUT $API/flows/$FLOW -H "Authorization: Bearer $TOKEN" -H 'If-Match: "2"' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Clinic intake","graph":'"$(jq .flow.graph /tmp/flow.json)"',
       "agent_settings":{"expected_draft_revision":1,"changes":{"call_behavior":{"ring_duration_ms":4000}}}}'
# expect 200 with agent_draft_revision 2; GET the agent (002) and confirm max_duration_s,
# webhook_timeout_ms and pronunciation entries are unchanged
# repeat with expected_draft_revision 1: expect 412 agent_draft_changed and flow revision unchanged
```

Browser checks:

1. Label a connection from the Agent node "Route To Billing!": the preview shows
   `route_to_billing`. Label it "!!!": inline refusal.
2. Select a node, press Delete: it disappears with its connections; click Undo in the notice.
   Press Backspace inside a text field: only text is removed.
3. Transfer node destination "12345": inline message; Save works; Publish lists
   `E_INVALID_FIELD`. Task max rounds 25: same behaviour.
4. Classify node with Sales and Support: two output handles; the connection panel offers a
   category list and no condition field; adding "sales" is refused.
5. Start node agent-first with a generated greeting pointing at a Say node: `E_GREETING_SOURCE`.
6. Open `/agents/<agent_id>/flow?configure=call-behavior`: Call behaviour opens with ring
   duration; switch who speaks first in Model and confirm the Start node changed.
7. Make an unsaved edit and start a test call: the save prompt appears first.
8. Ask the assistant to insert a node between two nodes: the new node does not overlap and the
   other nodes stay where they were.

## Results (2026-10-26, branch w3-flows, local stack on API 8103 and web 5183)

| Section | How it was run | Result |
|---|---|---|
| 1 Create | `tests/integration/flows/test_create_flow_agent.py`, contract tests, browser at `/agents/new/flow` | Pass: 201, three nodes and two edges, 0 errors, en-GB STT and TTS defaults; unknown language falls back to en-US with a warning |
| 2 Save | `test_save_revision.py`, browser save and conflict dialog | Pass: 200 then 412 `flow_revision_conflict` with `current_revision` 2; reload restores graph, positions and viewport |
| 3 Publish | `test_publish.py`, `test_validation.py`, browser publish dialog | Pass: `E_START_COUNT` and `W_UNREACHABLE` shown and selectable; 422 `flow_has_errors`; 201 with the compiled flow in the version; layout-only change keeps `graph_hash` (`test_compiler.py`) |
| 4 Runtime | `tests/harness/test_flow_scenarios.py` (real AgentSession in text mode, rule-driven fake model) | Pass: start, triage, route, support line, end with triggers always, llm_condition, category, always and `agent_hangup`; rule else, task max rounds, webhook failure, transfer fallback and the 200-move guard pass too. The read projection is covered by `test_flow_transitions_contract.py`. A live call with node highlighting needs LiveKit and was not run locally |
| 5 Overrides | `flow_overrides_context` scenario and `tests/unit/flow/test_opening.py` | Pass: the reset node's model requests carry no earlier caller turns; the Spanish node builds its own LLM (openai/gpt-5-mini) and STT (es) |
| 6 Assistant | `test_assistant.py`, `ProposalBar.test.tsx`, browser | Pass with the deterministic planner (no model key here): one added node, one removed and two added connections, decline leaves the graph unchanged, approve is one undo step, one `flow_assistant` charge, nothing charged on timeout |
| 7 Benchmarks | `bench_flow_engine`, `bench_flow_turn_latency` (results in `tests/harness/bench/results/`) | Pass: engine p95 0.02 ms per move; with a 350 ms model first token, turns without a move p50 355 ms against 357 ms single prompt, moves into a node with an entry line p50 358 ms. Real vendors were not available |
| 8 Walkthrough deltas | the curl above against the dev API, `test_save_with_agent_settings.py`, browser QA | Pass: 200 with `agent_draft_revision` 2 and other settings unchanged, then 412 `agent_draft_changed`; transition name preview, keyboard delete with Undo, transfer and max-rounds field errors, category handles, `?configure=call-behavior` and assistant placement checked in the browser |
