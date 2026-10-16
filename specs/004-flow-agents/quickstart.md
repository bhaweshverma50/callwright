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
uv run pytest tests/harness -k flow_triage_support -q
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
uv run python -m tests.harness.bench.bench_flow_engine --runs 500       # engine overhead
uv run python -m tests.harness.bench.bench_flow_turn_latency --set default
```

Pass criteria: engine overhead per move p95 at most 150 ms; flow agent turns on the default
stack p50 at most 800 ms and p95 at most 1500 ms, and no regression greater than 5% against the
single-prompt baseline on turns without a move. Results are written to
`services/voice-worker/tests/harness/bench/results/` and compared in CI.
