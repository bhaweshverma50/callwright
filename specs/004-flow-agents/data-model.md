# Data Model: Flow Agents

**Feature**: 004-flow-agents | **Date**: 2026-10-16 | **Plan**: [plan.md](./plan.md)

Owned module: `services/api/app/flows/`. Tables carry `workspace_id` with row-level security
(`USING (workspace_id = current_setting('app.workspace_id'))`), per architecture section 4.

## 1. Table `flows`

| Column | Type | Rules |
|---|---|---|
| id | text PK | `flw_` + ULID |
| workspace_id | text, not null | FK workspaces; RLS key |
| agent_id | text, not null, unique | FK agents (`agt_`), agent `type` must be `flow` |
| name | text, not null | 1 to 120 chars; set to the agent name at creation and renamed together with the agent (FR-048); never shown separately |
| graph | jsonb, not null | Flow Graph (section 2); validated on write |
| revision | integer, not null | starts at 1; +1 per successful save |
| last_validation | jsonb, not null | `{errors: int, warnings: int, issues: ValidationIssue[], validated_at}` |
| last_published_version_id | text, null | `agv_` of the newest version created by publish |
| created_at, updated_at | timestamptz | |
| updated_by | text | `usr_` |

Indexes: unique `(agent_id)`; `(workspace_id, updated_at desc)`.
Deleting an agent (002) cascades to its flow. Published versions keep their own copy (section 5).

## 2. Flow Graph (JSONB document)

```text
FlowGraph {
  nodes: Node[]            (1..200)
  edges: Edge[]            (0..500)
  viewport: {x: number, y: number, zoom: number (0.1..4)}
}

Node {
  id: string               pattern ^n_[a-z0-9]{8}$, unique in graph
  type: NodeType           start | agent | task | condition | say | extract_variable |
                           webhook | transfer | end
  label: string            1..80 chars
  position: {x: number, y: number}
  config: object           shape depends on type (section 2.1)
}

Edge {
  id: string               pattern ^e_[a-z0-9]{8}$, unique in graph
  source: string           node id
  target: string           node id
  trigger: Trigger         llm_condition | category | rule | else | always | success | failure
  label: string?           required for llm_condition only (not for always, success,
                           failure, category, rule, else); 1..60 chars; must contain a letter
                           or digit (E_TRANSITION_NAME_EMPTY)
  condition: string?       required for llm_condition; 1..1000 chars, plain language
  function_name: string?   optional override, ^route_to_[a-z0-9_]{1,48}$
  category: string?        required for category; must match a category name on the source;
                           chosen from a list in the UI; renamed with the category
  rule: Rule?              required for rule
  sort_order: integer      order among edges of the same source (rules evaluated in this order)
}

Rule { variable: string, operator: equals | not_equals | contains | matches | exists | gt | lt,
       value: string? (absent only for exists) }
```

### 2.1 Node config by type

| Type | Config fields (default) | Validation |
|---|---|---|
| start | `start_speaker`: `agent` \| `user` (`agent`); `greeting_type`: `static` \| `generated` (`static`); `greeting`: string ("Hi, thanks for calling. How can I help?") | `greeting` required when speaker is agent and type static; optional when speaker is user (played before listening, empty means silence; `greeting_type` ignored); max 500 chars. Agent plus `generated` requires the start edge target to be agent or task (E_GREETING_SOURCE). `start_speaker` is the only who-speaks-first setting for flow agents (FR-052) |
| agent | `instructions` (""); `begin_message` (null); `context_strategy`: `inherit` \| `summarize` \| `reset` (`inherit`); `overrides` (Overrides, all null); `tool_ids` ([]); `kb_search_enabled` (true) | instructions max 16,000; tool ids must exist in workspace |
| task | `instructions` (""); `fields`: TaskField[] (name and email example); `max_rounds` (5, 1..20); `context_strategy` (`inherit`); `overrides`; `tool_ids`; `kb_search_enabled` (true) | 1..30 fields; names snake_case, unique |
| condition | `kind`: `classify` \| `rule` (`classify`); `instructions` (""); `categories`: `{name, description}`[] | classify: 2..20 categories; name `^[A-Za-z0-9][A-Za-z0-9 _-]{0,59}$`, unique ignoring case (E_CATEGORY_NAME); rule: rules live on edges, `value` absent for `exists` |
| say | `message` (""); `allow_interruptions` (true) | message required, max 1,000 |
| extract_variable | `instructions` (""); `fields`: ExtractField[] | 1..30 fields; names snake_case, unique across flow-set variables. The editor converts typed names ("Customer Name" to `customer_name`) before adding (FR-056) |
| webhook | `request`: HttpRequestSpec (005); `mock_response` (null) | URL required, absolute, https (E_INVALID_FIELD); method set, timeout range and `speak_during_execution` (default true) per 005, identical to HTTP tools |
| transfer | `transfer`: TransferSpec (005) | static needs E.164 number (E_INVALID_FIELD when malformed); dynamic needs routing instructions |
| end | `message` ("Thanks for calling. Goodbye."); `reason` (`call_completed`, pattern `^[a-z_]{1,40}$`) | message max 500 |

```text
Overrides {
  llm: {provider, model, temperature (0..2)} | null      UI presets: Precise 0.2, Balanced 0.7, Creative 1.0
  tts: {provider, model, voice_id, speed (0.5..2), stability (0..1)} | null
  stt: {provider, model} | null
  language: string | null                                one of the 002 language codes
}
TaskField    { name, type: string | number | boolean | enum, description, required: bool,
               enum_values?: string[] }
ExtractField { name, type: string | number | boolean, description }
```

`HttpRequestSpec` and `TransferSpec` are defined in `services/api/app/tools/schemas.py` (005) and
imported, not redefined.

### 2.2 Allowed outgoing edges per node type

| Source type | Allowed triggers | Cardinality rules |
|---|---|---|
| start | always | exactly 1; target is agent, task or say; Start has no incoming edges |
| agent | llm_condition | 0..n (0 gives warning W_NODE_STALLS) |
| task | success, llm_condition | exactly 1 success; 0..n llm_condition |
| condition (classify) | category | exactly 1 per category; no others |
| condition (rule) | rule, else | 1..20 rule; exactly 1 else |
| say | always | exactly 1 |
| extract_variable | always | exactly 1 |
| webhook | success, failure | exactly 1 success; 0..1 failure (absent: failure follows success) |
| transfer | failure | 0..1 (absent gives warning W_TRANSFER_NO_FALLBACK) |
| end | none | 0 |

## 3. Validation Issue

```text
ValidationIssue { severity: error | warning, code: string, message: string,
                  node_id?: string, edge_id?: string, field?: string }
```

| Code | Severity | Condition |
|---|---|---|
| E_START_COUNT | error | number of start nodes is not 1 |
| E_START_EDGES | error | start has incoming edges, or not exactly 1 outgoing, or target type not allowed |
| E_DANGLING_EDGE | error | edge source or target does not exist |
| E_TRIGGER_NOT_ALLOWED | error | trigger not allowed for source type (table 2.2) |
| E_EDGE_CARDINALITY | error | cardinality rule in table 2.2 broken |
| E_MISSING_OUTGOING | error | say, extract_variable, webhook or condition with no outgoing edge |
| E_CATEGORY_EDGES | error | classify with < 2 categories or a category without exactly one edge |
| E_RULE_ELSE | error | rule condition without exactly one else edge |
| E_REQUIRED_FIELD | error | required config missing (say message, transfer destination, webhook URL, edge label or condition) |
| E_INVALID_SCHEMA | error | task or extract fields invalid |
| E_FUNCTION_NAME_CLASH | error | two transitions from one node derive the same name, or a name equals an attached tool name |
| E_END_HAS_EDGES | error | end node with outgoing edges |
| E_UNKNOWN_TOOL | error | node tool id not in workspace library |
| E_UNKNOWN_CATALOG | error | override provider, model, voice or language not in catalog |
| E_LIMIT | error | limits in research R18 exceeded |
| W_UNREACHABLE | warning | node not reachable from start |
| W_NO_INSTRUCTIONS | warning | conversational node with empty instructions and empty persona prompt |
| W_NODE_STALLS | warning | conversational node with no llm_condition or success edge |
| W_NO_EXIT | warning | reachable region with no path to an end or transfer node |
| W_TRANSFER_NO_FALLBACK | warning | transfer node without failure edge |
| W_END_NO_MESSAGE | warning | end node with empty message |
| W_UNSET_VARIABLE | warning | `{{var}}` used but never set and not built-in or defaulted |
| W_NO_BEGIN_MESSAGE | warning | conversational node entered by a transition and lacking an entry line (latency hint) |
| E_GREETING_SOURCE | error | start is agent-first with a generated greeting and its edge target is not agent or task |
| E_INVALID_FIELD | error | a constrained field is out of range or malformed: task `max_rounds` outside 1..20, transfer number not E.164, webhook URL not absolute https, timeout outside its range, schema, header, body template or canned response not valid JSON where JSON is required |
| E_CATEGORY_NAME | error | classify category name fails the pattern or duplicates another ignoring case |
| E_TRANSITION_NAME_EMPTY | error | llm_condition edge label yields an empty transition name |

Issue order: errors before warnings, then by node order in `graph.nodes`, then edge order.

## 4. Compiled Flow (`compiled_flow`, schema_version 1)

Produced by `flows/compiler.py`; JSON Schema exported to
`services/voice-worker/worker/flow/compiled_schema.json` and checked in CI.

```text
CompiledFlow {
  schema_version: 1
  flow_id: string, graph_hash: string (sha256 hex), compiled_at: datetime
  entry_node_id: string                          the start node
  persona_prompt: string
  builtin_variables: string[]
  declared_variables: {name, source_node_id, type}[]
  nodes: map<node_id, CompiledNode>
}

CompiledNode {
  type, label
  # conversational (agent, task)
  instructions: string                           persona prompt + node instructions, variables left as {{var}}
  begin_message: string | null
  context_strategy: inherit | summarize | reset
  llm: {provider, model, temperature}            fully resolved (override or agent default)
  tts: {provider, model, voice_id, speed, stability}
  stt: {provider, model}
  language: string
  tools: ToolSpec[]                              from tools.service.resolve_for_snapshot (005), secrets as refs
  kb_search: {enabled: bool, kb_ids: string[]}
  transitions: {edge_id, function_name, description, target_node_id, trigger}[]
  task: {json_schema: object, max_rounds: int, success_target: node_id} | null
  # non-conversational
  start: {start_speaker, greeting_type, greeting, next: node_id} | null
  say: {message, allow_interruptions, next: node_id} | null
  condition: {kind, instructions, categories: {name, description, target}[],
              rules: {edge_id, variable, operator, value, target}[], else_target} | null
  extract: {instructions, json_schema: object, next: node_id} | null
  webhook: {request: HttpRequestSpec, mock_response, success_target, failure_target} | null
  transfer: {transfer: TransferSpec, failure_target: node_id | null} | null
  end: {message, reason} | null
}
```

Transition description text: `"Go to <target label>. Use when: <edge condition>"`.

Transition name derivation (FR-044, research R7): lowercase the label, replace every run of
characters outside `[a-z0-9]` with `_`, trim `_`, drop a leading `route_to_` so the prefix is not
doubled, cut to 48 characters, then prefix `route_to_`. "Route To Billing!" and "Route to
billing" both give `route_to_billing`; "!!!" gives an empty slug (E_TRANSITION_NAME_EMPTY). The
edge panel preview uses a TypeScript copy of this one function, kept identical to the Python one
by shared vectors in `services/api/tests/unit/flows/fixtures/transition_names.json` (same
approach as 005's HTTP vectors).

## 5. AgentVersion config extension (002 snapshot)

For agents of type `flow`, the snapshot created at publish includes:

```text
config.flow = {
  flow_id: "flw_...",
  name: string,
  graph: FlowGraph,          source graph at publish time (positions included, for restore)
  graph_hash: string,        excludes positions and viewport
  compiled: CompiledFlow
}
```

`config.prompt` is the persona prompt. `config.begin_message` and `config.start_speaker` are
ignored for flow agents; the start node is authoritative and the compiler copies its values into
`compiled.nodes[start]`.

## 6. Call event payloads (rows in 003's `call_events`)

```text
kind = "flow_node_entered"
payload { node_id, node_type, node_label, turn_index, t_ms }

kind = "flow_transition"
payload { from_node_id, from_label, to_node_id, to_label, edge_id, edge_label,
          trigger: llm_condition | category | rule | else | always | success | failure | fallback,
          function_name?, turn_index, t_ms, engine_ms, model_ms? }

kind = "flow_task_completed"
payload { node_id, values: object, complete: bool, rounds: int }

kind = "flow_variables_set"
payload { node_id, source: extract | task | webhook, variables: object }
```

`t_ms` is milliseconds since call start; `engine_ms` is executor time for the move; `model_ms` is
model time spent deciding (classify call or transition tool call). Read projection
`GET /v1/calls/{call_id}/flow-transitions` returns `flow_transition` rows ordered by event
sequence. Partial index `call_events (call_id, seq) WHERE kind LIKE 'flow_%'` (migration owned by
this feature, on 003's table).

## 7. Assistant proposal (not persisted)

```text
AssistantRequest  { messages: {role: user | assistant, content}[] (1..50),
                    base_revision: int, graph?: FlowGraph }
AssistantResponse { message: string, flow_name?: string, operations: Operation[],
                    proposed_graph: FlowGraph, issues: ValidationIssue[], base_revision: int,
                    usage: {input_tokens, output_tokens, cost_usd} }

Operation (one of)
  {op: add_node, node: Node}                              id already remapped to n_*
  {op: update_node, node_id, changes: {label?, config? (deep-merged)}}
  {op: remove_node, node_id}                              connected edges listed as remove_edge ops too
  {op: add_edge, edge: Edge}
  {op: update_edge, edge_id, changes: {label?, condition?, target?, category?, rule?}}
  {op: remove_edge, edge_id}
  {op: rename_flow, name}
```

Node configs proposed by the assistant never contain `overrides`. Proposals are not stored; the
chat history lives in the browser session only.

Placement (FR-049): the request graph carries positions. For each added node the server sets
`position` after applying the operations: between its source and target when it is inserted on an
edge, otherwise one rank (`ranksep` 120 px) to the right of its first connected neighbour,
shifted down by 40 px steps until its bounding box (assumed 240 x 96 px) overlaps no node.
Existing nodes are never moved.

## 8. Runtime state (worker memory, per call)

```text
FlowRunState { current_node_id, visited: node_id[], variables: map, task_rounds: map<node_id,int>,
               summary: string | null, transition_count: int }
```

Node lifecycle inside the executor: `entered -> running -> (waiting_for_caller) -> exiting ->
transitioned`. End and successful transfer nodes are terminal. A guard of 200 transitions per call
ends the call with disconnect reason `error` to stop runaway loops between non-conversational
nodes.

## 9. Atomic save with flow-wide settings (FR-046, FR-048)

`PUT /v1/flows/{flow_id}` accepts an optional `agent_settings` block:

```text
SaveFlowRequest {
  name: string                         becomes the agent name too (002 rename, same transaction)
  graph: FlowGraph
  agent_settings?: {
    expected_draft_revision: int       the 002 agent draft revision the editor loaded
    changes: object                    partial AgentConfig (002); only fields the user changed
  }
}
```

The service opens one transaction: checks the flow `If-Match` revision, checks
`expected_draft_revision` against 002's draft, deep-merges `changes` into the current draft
config through `agents.service.update_draft(agent_id, patch, expected_revision)` (fields not in
`changes` keep their stored values; `null` in `changes` clears a nullable field explicitly), then
writes the graph and name. Any failure rolls back both. Keys outside AgentConfig, and
`start_speaker` or `begin_message` (owned by the Start node for flow agents), are rejected with
422. The response is the Flow plus `agent_draft_revision`. Conflicts return 412 with code
`flow_revision_conflict` or `agent_draft_changed`.
