# Feature Specification: Flow Agents

**Feature Branch**: `004-flow-agents`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Flow agent creation (name and language, seeded voice and speech-recognition defaults), a canvas builder with auto-layout and 9 node types (start, agent, task, condition, say, extract variable, webhook, transfer, end), per-node prompt, model, tools and variable extraction, edges whose natural-language conditions become transitions the model can choose, flow-level global settings, validation (reachability, single start, dangling edges), a compile step whose output is stored with the published agent version, a runtime flow executor, flow transitions recorded per call, and an AI flow assistant whose proposed add/update/remove operations are reviewed as a diff before they are applied."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create a flow agent and design its graph (Priority: P1)

An operator chooses "Flow" as the agent type, enters a name and a language, and lands on a canvas
that already holds a working starter graph (Start, one conversational Agent node, End, connected).
Voice and speech-recognition defaults are filled in for the chosen language. The operator drags
nodes from a palette of nine types, connects them, writes a plain-language condition on each
connection ("caller asks about a bill"), edits each node in a side panel, tidies the canvas with
one-click auto-layout, and saves a draft.

**Why this priority**: Flow agents exist to let non-programmers design branching conversations;
without a canvas and a saved graph nothing else in this feature has input.

**Independent Test**: Create a flow agent named "Clinic intake" in English (UK), add a Say node and
a Condition node, connect them with labelled edges, auto-layout, save, reload the page and confirm
the graph, labels, node settings and viewport come back exactly as saved.

**Acceptance Scenarios**:

1. **Given** the agent-type chooser, **When** the operator picks Flow and submits a name and
   language, **Then** a flow agent is created with that language's default voice and
   speech-recognition settings, and the canvas opens with Start, Agent and End nodes already
   connected.
2. **Given** an empty name, **When** the operator submits, **Then** creation is refused with
   "Agent name is required" and nothing is created.
3. **Given** an open canvas, **When** the operator drags any of the nine node types onto it,
   **Then** the node appears with its default label and default settings and opens in the side
   panel.
4. **Given** two nodes, **When** the operator connects them, **Then** the connection asks for a
   short label and a condition in plain language, and shows a preview of how the agent will see
   that choice ("Go to Billing. Use when: caller asks about a bill").
5. **Given** a messy canvas, **When** the operator clicks Auto-layout, **Then** nodes are arranged
   left to right in reading order without overlaps, and Fit to screen frames the whole graph.
6. **Given** unsaved edits, **When** the operator tries to leave the page, **Then** they are asked
   to stay or leave without saving.
7. **Given** the same flow open in two tabs, **When** the second tab saves after the first,
   **Then** the second save is refused with a message to reload, and no edits are silently lost.
8. **Given** a connection leaving an Agent node, **When** the operator labels it
   "Route To Billing!", **Then** the preview shows the transition name `route_to_billing`
   exactly as the model will see it; a label made only of symbols ("!!!") is refused with
   "The label needs at least one letter or digit".
9. **Given** a selected node and focus outside any text field, **When** the operator presses
   Delete or Backspace, **Then** the node and its connections are removed without a
   confirmation, and a notice offers Undo, which restores both in one step.
10. **Given** a Transfer node, **When** the operator enters "12345" as the destination and
    leaves the field, **Then** the field explains that an international number such as
    +14155550100 is needed; the draft still saves, and publishing is blocked until it is fixed.
11. **Given** unsaved canvas edits and a changed flow-wide setting, **When** the operator saves
    and the save fails, **Then** neither the graph nor the setting is stored; and on any save,
    flow-wide settings the operator did not touch keep their stored values.
12. **Given** a classify Condition node with categories Sales and Support, **When** it is shown
    on the canvas, **Then** it has one output handle per category, each connection from it names
    its category and explains that routing is decided by the node (no condition field), and
    adding "sales" as a third category is refused as a duplicate.
13. **Given** unsaved changes, **When** the operator starts a test call from the builder,
    **Then** the draft is saved first (or the operator cancels), so the test runs exactly what is
    on the canvas.

---

### User Story 2 - Validate and publish a flow (Priority: P1)

Before a flow can take calls, the operator sees a list of problems grouped as errors (block
publishing) and warnings (allowed). Clicking a problem selects the node or connection at fault.
Publishing turns the graph into a compiled, runnable form and stores it inside a new immutable
agent version together with the graph it came from, so every call can be traced to the exact flow
it ran.

**Why this priority**: A flow that can reach a dead end or has two entry points produces broken
calls; publishing is the gate that keeps live traffic safe.

**Independent Test**: Build a flow with a second Start node and an unreachable Say node; confirm
publish is refused with one error and one warning; fix the error; publish; confirm a new version
exists whose stored config contains both the graph and the compiled form, and that the version
history labels it as a flow change.

**Acceptance Scenarios**:

1. **Given** a flow with two Start nodes, **When** the operator publishes, **Then** publishing is
   refused with "A flow needs exactly one Start node" and the extra Start node is highlighted.
2. **Given** a connection whose target node was deleted, **When** the flow is validated, **Then**
   the dangling connection is reported as an error and can be removed from the problem list.
3. **Given** a node no path from Start reaches, **When** the flow is validated, **Then** a warning
   names that node and publishing is still allowed.
4. **Given** two connections leaving one node that would produce the same transition name,
   **When** the flow is validated, **Then** an error asks the operator to rename one of them.
5. **Given** a flow with no errors, **When** the operator publishes with release notes, **Then** a
   new agent version is created, new calls use it, and the success message reports how many
   warnings remain.
6. **Given** a published version, **When** the operator later edits the draft, **Then** live calls
   keep using the published version until the next publish.
7. **Given** a Start node set to a model-written greeting whose connection leads to a Say node,
   **When** the flow is validated, **Then** an error explains that the greeting must come from an
   Agent or Task node.
8. **Given** a Task node with max rounds 25, a Webhook with URL "notaurl" and an Agent node
   with empty instructions while the persona prompt is set, **When** the operator publishes,
   **Then** the first two are reported as errors on their fields and publishing is refused; the
   Agent node is accepted.

---

### User Story 3 - Callers move through the flow (Priority: P1)

During a call the agent behaves according to the node it is in: conversational nodes talk with
their own instructions, Say nodes speak a fixed line, Condition nodes route silently, Extract and
Task nodes capture data, Webhook nodes call an outside system, Transfer nodes hand the caller to a
person, and End nodes close the call. The agent moves between nodes when the model judges that a
connection's condition is met (or immediately, for non-conversational nodes). Every move is
recorded on the call, the canvas highlights the active node during a test call, and the call
detail shows the path taken.

**Why this priority**: This is the product promise of flow agents; without it the canvas is a
drawing.

**Independent Test**: Publish a flow Start, Agent "Triage", Condition "Route" (Sales, Support),
Say "Support line", End; run a scripted caller that asks for support; confirm the call visits
Start, Triage, Route, Support line, End in that order, each move is recorded with its trigger and
time, and the call ends with reason "agent hangup".

**Acceptance Scenarios**:

1. **Given** a Start node set to "agent speaks first" with a fixed greeting, **When** the call
   connects, **Then** the greeting is spoken without waiting for the model.
2. **Given** an Agent node with two outgoing connections, **When** the caller's request matches
   one condition, **Then** the agent moves to that connection's target and the move is recorded
   with the connection label.
3. **Given** a Condition node of the "classify" kind with categories Sales and Support, **When**
   it is entered, **Then** the agent picks exactly one category from the conversation and follows
   that category's connection without speaking.
4. **Given** a Condition node of the "rule" kind (`task_result.age` greater than 17), **When** the
   rule does not match, **Then** the "otherwise" connection is followed.
5. **Given** a Task node collecting name and email, **When** the caller has given both, **Then**
   the values become available to later nodes, and after 5 unanswered rounds the node completes
   with whatever it has.
6. **Given** a Webhook node whose request fails or times out, **When** it runs, **Then** the
   failure connection is followed if one exists, otherwise the call continues on the success path
   with the failure noted in the call record.
7. **Given** a test call from the builder, **When** the agent enters a node, **Then** that node is
   highlighted on the canvas within 1 second.
8. **Given** a finished call on a flow agent, **When** the operator opens the call, **Then** they
   see the ordered list of node moves (from, to, connection, trigger, time into call).

---

### User Story 4 - Tune nodes and flow-wide defaults (Priority: P2)

The operator sets flow-wide defaults once (model, voice, speech recognition, call behaviour,
shared tools, knowledge bases, a shared persona prompt) and overrides them only where a node needs
something different: a stronger model for a hard question, a different voice or language for one
step, a clean conversation history after a handoff, or tools that only one node may use.

**Why this priority**: Real flows need per-step tuning, but the defaults alone already produce a
working agent.

**Independent Test**: Set the flow default model to a fast model, override one Agent node to a
larger model and Spanish, attach a tool only to that node; run a call through both nodes and
confirm each turn used the expected model, language and tool set.

**Acceptance Scenarios**:

1. **Given** a node with "use agent default" for the model, **When** the flow default model is
   changed, **Then** that node uses the new default on the next publish.
2. **Given** a node with context set to "reset", **When** the call moves into it, **Then** the
   model in that node does not see earlier conversation turns, only the persona prompt, node
   instructions and captured variables.
3. **Given** a node with context set to "summarize", **When** the call moves into it, **Then** the
   node receives a short summary of earlier turns instead of the full history, without an audible
   pause at the handoff.
4. **Given** a tool attached only to one node, **When** the call is in any other conversational
   node, **Then** that tool cannot be used there.
5. **Given** knowledge bases attached at flow level, **When** the call is in any conversational
   node, **Then** the agent can search them, unless that node has knowledge search turned off.
6. **Given** a link to the builder ending in `?configure=call-behavior`, **When** it is opened,
   **Then** the flow-wide settings open directly on Call behaviour, which includes ring duration
   with the same range as the single-prompt editor.
7. **Given** a workspace with no tools, **When** the operator opens an Agent node, **Then** the
   tools section is still shown, with an empty state and a shortcut to create a tool.
8. **Given** the Start node set to "agent speaks first", **When** the operator switches who speaks
   first in the flow-wide settings, **Then** the Start node shows the new value, because both
   controls edit the same setting.
9. **Given** a node voice override on one provider with a voice chosen, **When** the operator
   switches the override to another provider, **Then** the voice and voice model are cleared and
   must be chosen again.

---

### User Story 5 - Build or change a flow with the AI assistant (Priority: P3)

The operator describes what they want ("add a step that collects the caller's date of birth before
booking, and send billing questions to a human") in a chat beside the canvas. The assistant replies
with a short explanation and a set of proposed changes shown on the canvas as a diff: added items
in green, removed items struck through in red, changed items outlined. The operator approves or
declines the whole set; nothing changes until they approve, and declining restores the canvas
exactly.

**Why this priority**: It speeds up authoring and helps new users, but manual editing already
covers every capability.

**Independent Test**: On a three-node flow, ask the assistant to add a date-of-birth Task node
between two existing nodes; confirm the proposal shows one added node, one removed connection and
two added connections; decline and confirm the graph is unchanged; ask again and approve; confirm
the draft now matches the proposal and validates.

**Acceptance Scenarios**:

1. **Given** a pending proposal, **When** the operator tries to edit the canvas or send another
   message, **Then** they are told to approve or decline the pending changes first.
2. **Given** a proposal that would leave the flow with an error, **When** it is shown, **Then** the
   resulting errors are listed with the proposal before the operator decides.
3. **Given** an approved proposal, **When** it is applied, **Then** it becomes part of the draft
   and can be undone with one undo step.
4. **Given** an assistant request, **When** it completes, **Then** the request is charged as a
   feature usage line for the workspace.
5. **Given** the assistant does not answer within 60 seconds, **When** the time passes, **Then**
   the operator sees a retry option and the canvas is unchanged.
6. **Given** a proposal that inserts a node between two existing nodes, **When** it is shown,
   **Then** the new node sits between its neighbours without overlapping any node, and existing
   nodes keep their positions.

---

### Edge Cases

- A flow with a cycle and no path to an End or Transfer node: warning "calls can only end by
  hang-up or time limit"; publishing allowed.
- The model calls no transition and the caller keeps talking: the agent stays in the node; the
  call still ends through the silence and maximum-duration limits of the agent.
- The model tries to call two transitions in one turn: only the first is honoured and the second
  is reported back to the model as ignored.
- A node override names a model, voice or speech provider that is no longer in the catalog:
  publishing is blocked with an error naming the node and field.
- A Transfer node is reached on a web or chat-app call where transfers are not possible: its
  failure connection is followed, or the agent says the transfer is unavailable and continues.
- A variable used in a node's text (`{{dob}}`) is never set by any earlier node and has no
  default: warning at validation; at runtime it is replaced with an empty string and noted on the
  call.
- A Task node's schema is changed after calls ran: old calls keep the values they captured; only
  new versions use the new schema.
- An assistant proposal refers to a node the operator deleted while waiting: the proposal is
  rejected as out of date and the operator is asked to resend.
- A very large flow (over 200 nodes or 500 connections): saving is refused with the limit stated.
- A published flow references a tool that was later deleted: the published version keeps working
  with its stored copy; the draft shows the reference as missing.
- A connection label that already starts with "Route to" ("Route to billing") yields
  `route_to_billing`, not a doubled prefix.
- A classify category is renamed after its connection exists: the connection follows the
  rename. A category is deleted: its connection is reported as an error until removed or
  reassigned.
- The header name is emptied: an inline message asks for a name and Save stays disabled.
- The operator presses Backspace while typing in a node field: only text is deleted, never the
  node.
- A save carries a flow-wide settings change while another user saved the agent draft in the
  meantime: the whole save is refused with a reload message, and nothing is stored.

## Requirements *(mandatory)*

### Functional Requirements

**Creation and canvas**

- **FR-001**: Users MUST be able to create a flow agent from a name (required) and a language;
  the agent's voice and speech-recognition settings MUST be seeded from that language's defaults.
- **FR-002**: The agent type (flow or single-prompt) MUST NOT be changeable after creation.
- **FR-003**: A new flow agent MUST start with a connected Start, Agent and End graph that
  validates without errors.
- **FR-004**: The canvas MUST offer the nine node types: start, agent, task, condition, say,
  extract variable, webhook, transfer and end, each with the default label and settings in the
  Node Types table below.
- **FR-005**: The canvas MUST support drag from palette, connect, select, multi-select, delete,
  duplicate node, pan, zoom, fit to screen, undo/redo for at least 50 steps, and one-click
  left-to-right auto-layout without overlapping nodes.
- **FR-006**: Users MUST be able to save a draft at any time, including a draft with errors; the
  saved draft MUST include node positions and the viewport.
- **FR-007**: Saves MUST be rejected when the draft changed since the user loaded it, and the
  user MUST be told to reload.
- **FR-008**: The builder MUST warn before leaving with unsaved changes.

**Nodes**

- **FR-009**: Conversational nodes (agent, task) MUST each have their own instructions and MAY
  override model, model temperature, voice, voice speed, voice stability, speech recognition and
  language, each with a "use agent default" option.
- **FR-010**: Conversational nodes MUST support a context strategy of `inherit` (full history,
  default), `summarize` (summary of earlier turns) or `reset` (no earlier turns).
- **FR-011**: Conversational nodes MUST let the user pick tools from the workspace tool library;
  tools attached at flow level MUST be available in every conversational node in addition.
- **FR-012**: A Task node MUST capture data described by a structured schema of named fields,
  complete when all required fields are captured or after a maximum number of caller rounds
  (default 5, range 1 to 20), and expose the result to later nodes as `task_result.<field>`.
- **FR-013**: A Condition node MUST support two kinds: "classify" (the model picks exactly one of
  2 or more named categories, each with one outgoing connection) and "rule" (ordered comparisons
  on a variable with operators equals, not equals, contains, matches pattern, exists, greater
  than, less than, plus a required "otherwise" connection).
- **FR-014**: A Say node MUST speak a fixed message without the model and MAY forbid
  interruptions.
- **FR-015**: An Extract Variable node MUST run one silent model pass over the conversation and
  store named fields (lowercase with underscores; types text, number, true/false), each with a
  description, as variables usable later as `{{name}}`.
- **FR-016**: A Webhook node MUST call an outside HTTP endpoint using the same request settings
  as custom HTTP tools (method, URL, headers with secret values masked, body template, timeout,
  response-to-variable mapping, a message spoken while waiting) and MAY have separate success and
  failure connections. It MUST support a canned response used in simulations.
- **FR-017**: A Transfer node MUST use the same transfer settings as the transfer tool (fixed or
  model-chosen destination, cold or warm handoff with private or public briefing, hold message)
  and MAY have a failure connection.
- **FR-018**: An End node MUST speak an optional closing message (default "Thanks for calling.
  Goodbye.") and end the call with a recorded reason (default `call_completed`).
- **FR-019**: The Start node MUST define who speaks first (agent or caller) and, when the agent
  speaks first, whether the greeting is a fixed line or written by the first conversational node.

**Connections and transitions**

- **FR-020**: Each connection leaving a conversational node MUST have a short label and a
  plain-language condition; the system MUST turn it into a choice the model can make, named from
  the label and described by the condition, and show the user a preview of that choice.
- **FR-021**: Connections leaving other node types MUST use the trigger that fits the node:
  category (classify), rule or otherwise (rule), success or failure (webhook, transfer), or
  always (start, say, extract variable).
- **FR-022**: Transition names MUST be unique per source node and MUST NOT clash with tool names
  attached to that node.

**Flow-wide settings**

- **FR-023**: Users MUST be able to edit flow-wide defaults from the builder: model, voice,
  speech recognition, call behaviour, shared tools, knowledge bases, quality checks and a shared
  persona prompt added to every conversational node.

**Validation**

- **FR-024**: The system MUST validate the graph on every save and on request, and report each
  issue with a severity (error or warning), a code, a message and the node or connection it
  concerns.
- **FR-025**: Errors MUST include at least: not exactly one Start node; Start with other than one
  outgoing connection or with incoming connections; connections whose source or target does not
  exist; non-End nodes with no outgoing connection where the node cannot wait for the caller (say,
  extract variable, webhook, condition); classify Condition with fewer than 2 categories or a
  category without exactly one connection; rule Condition without an "otherwise" connection; Say
  without a message; Transfer without a destination; Webhook without a valid URL; Task with an
  invalid schema; conversational connection without label or condition; duplicate or clashing
  transition names; End node with outgoing connections; references to unknown tools or catalog
  entries; graph size over 200 nodes or 500 connections.
- **FR-026**: Warnings MUST include at least: nodes unreachable from Start; conversational nodes
  with no instructions and no persona prompt; conversational nodes with no outgoing connection
  ("the call will stay in this node"); regions with no path to an End or Transfer node; Transfer
  without a failure connection; End without a closing message; variables used but never set.

**Compile and publish**

- **FR-027**: Publishing MUST be refused while any error exists.
- **FR-028**: Publishing MUST produce a compiled, self-contained form of the flow (resolved
  defaults, tools, transitions and prompts per node) and store it, with the source graph and a
  fingerprint of that graph, in a new immutable agent version.
- **FR-029**: Calls MUST run the compiled form stored in the version they were started with;
  editing the draft MUST NOT affect calls on published versions.
- **FR-030**: Users MUST be able to request a compile preview without publishing, showing what
  each node's model will receive.

**Runtime**

- **FR-031**: The call runtime MUST execute the compiled flow as a state machine starting at
  Start, applying each node type's behaviour described in User Story 3.
- **FR-032**: Each node move MUST be recorded on the call with: from node, to node, connection,
  trigger kind, turn number, time since call start and the time the move took.
- **FR-033**: During builder test calls the runtime MUST announce node entries so the canvas can
  highlight the active node.
- **FR-034**: Users MUST be able to see the ordered list of node moves for any call of a flow
  agent; for single-prompt agents the list MUST be empty.
- **FR-035**: Flow moves MUST NOT add audible delay beyond the agent's normal turn time when the
  target node starts with a fixed line.

**AI assistant**

- **FR-036**: Users MUST be able to chat with an assistant that sees the current draft graph and
  replies with a message and a list of proposed operations: add node, update node, remove node,
  add connection, update connection, remove connection, rename flow.
- **FR-037**: Proposed operations MUST be shown as a diff on the canvas, together with the
  validation result of the graph after applying them, and MUST change the draft only after the
  user approves; declining MUST restore the canvas exactly.
- **FR-038**: The assistant MUST NOT set per-node model or provider overrides; added nodes use
  the flow defaults.
- **FR-039**: Each assistant request MUST be metered as a feature charge.

**Builder details (live UI walkthrough, 2026-10-16)**

- **FR-040**: The canvas MUST offer a toolbar with Auto-layout, Fit to screen, zoom in and zoom
  out; every icon-only control MUST have an accessible name and a visible tooltip.
- **FR-041**: Delete and Backspace MUST delete the selected nodes and connections when focus is
  not in a text field. Deleting MUST NOT ask for confirmation, but MUST be one undo step and MUST
  offer Undo in a notice.
- **FR-042**: When the caller speaks first, the Start node MUST allow an optional short greeting
  played before listening (empty means silence). When the agent speaks first with a model-written
  greeting, the Start connection MUST lead to an Agent or Task node (otherwise an error), and the
  panel MUST say that the greeting comes from that node's instructions. The Start card MUST show
  who speaks first.
- **FR-043**: Classify category names MUST be 1 to 60 characters of letters, digits, spaces,
  hyphens or underscores and unique ignoring case; invalid or duplicate entries MUST be refused
  inline with the reason. A classify node MUST show one output handle per category; a connection
  from it MUST carry a category chosen from the node's list (not typed) and MUST explain that
  the node decides the route instead of asking for a condition. Renaming a category MUST carry
  its connection along.
- **FR-044**: The connection panel MUST show the exact transition name the model will see,
  derived from the label (lowercase, every run of other characters becomes one underscore,
  trimmed, at most 48 characters, prefixed `route_to_` once even when the label already starts
  with "route to"). A label that yields an empty name MUST be refused. Only connections the
  model chooses (leaving Agent or Task nodes) need a label; connections leaving Start, Say and
  Extract nodes MUST NOT require one.
- **FR-045**: Node panels MUST check constrained fields while they are edited (number ranges such
  as Task max rounds 1 to 20 and webhook timeout, international phone format for transfer
  numbers, absolute https URLs for webhooks, JSON syntax for schemas, headers, body templates and
  canned responses) and show the reason next to the field. The same checks MUST be publish
  errors, so a draft with bad values saves but never publishes.
- **FR-046**: One Save MUST store the graph and any changed flow-wide settings together: all are
  stored or none is. A save MUST carry only the settings the user changed and MUST NOT reset
  settings the user did not touch (for example maximum call duration, ring duration, webhook
  timeout, pronunciation entries or analysis model).
- **FR-047**: Starting a builder test call with unsaved changes MUST save first (or let the user
  cancel), so the test always runs what is on the canvas.
- **FR-048**: A flow agent MUST show one name: the flow takes the agent's name at creation, and
  renaming in the builder header renames the agent; an empty name MUST be refused inline.
- **FR-049**: The assistant MUST receive node positions. Nodes it adds MUST be placed next to their
  connected neighbours without overlapping existing nodes, and existing nodes MUST keep their
  positions.
- **FR-050**: Flow-wide settings MUST be organised in sections Model, Voice, Call behaviour,
  Functions, Advanced, Knowledge base and Quality checks. Each section MUST be addressable by link
  (`?configure=model|voice|call-behavior|functions|advanced|knowledge-base|quality-checks`), and
  the open section MUST be kept in the address. Advanced MUST include webhook, voicemail, keypad
  input, background audio, pronunciation, the post-call analysis model and the analysis
  variables editor (owned by 007).
- **FR-051**: Each settings section MUST state how it saves: sections that belong to the agent
  draft (model, voice, call behaviour, advanced) save with the builder Save and mark unsaved
  changes; sections that edit shared records (functions, knowledge attachments, quality checks,
  analysis variables) save immediately and confirm it.
- **FR-052**: Flow-wide settings MUST include every agent setting that applies to flow agents,
  with the same ranges as the single-prompt editor, including ring duration. "Who speaks first"
  MUST have one source: changing it in flow-wide settings changes the Start node, and the reverse.
- **FR-053**: Conversational nodes MUST always show the tool picker; when the workspace library is
  empty it MUST show an empty state with a shortcut to create a tool.
- **FR-054**: In node overrides, changing the voice provider MUST clear the chosen voice and voice
  model; a model with a fixed temperature MUST show that fixed value with the control disabled;
  the language override MUST drive the node's speech-recognition model choice.
- **FR-055**: Task fields MUST be editable as a field list or as JSON Schema text; JSON errors MUST
  show while typing with the line and reason, and switching views MUST keep the fields.
- **FR-056**: In rule conditions the value input MUST be hidden for the "exists" operator. In
  Extract nodes a typed variable name MUST be converted to lowercase with underscores and shown
  before it is added, duplicates MUST be refused, and the node MUST list the `{{name}}`
  placeholders it makes available to later nodes.
- **FR-057**: Node cards MUST show a one-line summary of their key setting (who speaks first,
  overridden model, field count, transfer type and number, start of the message), and multiline
  fields MUST offer an expanded editor.
- **FR-058**: The builder header MUST show the editable name, a copyable agent ID, the current
  version with access to version history (002), flow-wide settings, Save and Publish. With
  nothing selected the side panel MUST show the assistant and test tabs; selecting a node or
  connection MUST replace them with its settings, and clicking the empty canvas MUST bring them
  back.

### Node Types

| Type | Default label | Key settings (defaults) |
|---|---|---|
| start | Start | who speaks first (agent); greeting kind (fixed line); greeting text |
| agent | Agent | instructions; entry line; context (inherit); overrides; tools; knowledge search (on) |
| task | Collect details | instructions; field schema; max rounds (5); context (inherit); tools |
| condition | Route | kind (classify); categories or rules |
| say | Say | message; allow interruptions (on) |
| extract_variable | Extract | instructions; fields |
| webhook | API call | request settings; message while waiting; canned response |
| transfer | Transfer | destination; cold or warm; hold message |
| end | End | closing message; end reason (`call_completed`) |

### Key Entities

- **Flow**: the editable graph of one flow agent; name, nodes, connections, viewport, persona
  prompt, revision number, last validation result. Exactly one per flow agent.
- **Node**: one step in the flow; type, label, position and type-specific settings.
- **Connection (edge)**: a directed link between two nodes; label, condition or trigger, order.
- **Validation Issue**: severity, code, message, related node or connection.
- **Compiled Flow**: the runnable form stored inside an agent version; per-node resolved settings
  and transitions, entry node, graph fingerprint, schema version.
- **Flow Transition (call record)**: one node move on one call; from, to, connection, trigger,
  turn, timing.
- **Assistant Proposal**: the assistant's reply for one request; message, operations, resulting
  validation issues, base revision.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user creates a flow agent and places a first test call on the starter graph in
  under 3 minutes.
- **SC-002**: An operator builds a 10-node flow with branches and publishes it in under 20 minutes
  without reading documentation, in moderated usability tests with 5 participants.
- **SC-003**: 100% of graphs with any error listed in FR-025 are refused at publish in automated
  tests; 0 valid reference graphs are refused.
- **SC-004**: On the benchmark call set, flow agents meet the platform turn-latency targets (p50 at
  most 800 ms, p95 at most 1500 ms) on turns without a node move and on moves into nodes with a
  fixed entry line; the flow engine itself adds at most 150 ms at p95 per move, not counting time
  spent waiting for the model.
- **SC-005**: 100% of node moves in benchmark calls appear in the call record in order, with no
  duplicates.
- **SC-006**: The active node highlight appears within 1 second of the move in 95% of test calls.
- **SC-007**: At least 80% of assistant proposals on the reference prompt set validate without
  errors after approval.
- **SC-008**: Auto-layout of a 100-node flow completes in under 1 second in the browser.

## Assumptions

- One flow per flow agent; multiple flows per agent and shared sub-flows are out of scope for v1.
- The persona prompt is the agent's main prompt field; for flow agents it is prepended to every
  conversational node's instructions.
- Flow-wide model, voice, speech, call behaviour, tool and knowledge settings are the agent's
  normal settings (agent builder feature); this feature adds only the graph and persona use.
- Language defaults (voice, voice model, speech-recognition provider and model per language) come
  from the agent builder's catalog; this feature only applies them at creation.
- Custom HTTP request settings, transfer settings, the tool library and knowledge search come from
  the tools and knowledge feature; flow nodes reuse them rather than defining their own.
- Builder test calls run the current draft through the voice runtime's test-call path; the draft
  must compile without errors to start a test call.
- The assistant uses the platform's default model; operators cannot pick the assistant model.
- Transfers and keypad tones are available only on phone calls.
- Whether a flow takes live calls is decided by the published and pinned agent version (002);
  the flow itself carries no separate active flag.
- Right-click menus and a minimap are not provided in v1; every action is reachable from the
  side panel, the toolbar or the keyboard.
