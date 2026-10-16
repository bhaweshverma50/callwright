# Feature Specification: Tools and Knowledge

**Feature Branch**: `005-tools-knowledge`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Tools an agent can call during a live call (end the call, transfer it to a person with a cold or warm handoff, press keypad digits on an IVR, and call a customer's own HTTP API with typed parameters, a timeout, response mapping and something to say while it waits), canned responses for simulations, attachment to agents and flow nodes, masked secrets; and knowledge bases: upload PDF and DOCX documents (20 MB limit) with duplicate detection, background ingestion with visible status, attachment to agents, live retrieval during calls within a latency budget, short-lived document links, and delete with detach."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Give an agent call-control tools (Priority: P1)

An operator building an agent adds tools from the agent's Tools tab: "end call" (with an optional
goodbye line), "transfer call" (to a fixed number, or to a number the agent picks from routing
instructions, as a cold handoff or a warm handoff where the agent briefs the person first) and
"press digit" (for navigating a phone menu). Each tool has a name the agent uses, a description
that tells the agent when to use it, and type-specific settings. Tools live in a workspace
library, so the same "transfer to billing" tool can be attached to several agents.

**Why this priority**: Ending and transferring calls are the minimum a production phone agent
needs; without them every call ends by silence timeout or by the caller hanging up.

**Independent Test**: Create an end-call tool and a static cold transfer tool, attach both to an
agent, place a scripted phone call that asks for a human, and confirm the call is handed to the
configured number and recorded with the "call transfer" disconnect reason; repeat with "goodbye"
and confirm the goodbye line is spoken before the agent hangs up.

**Acceptance Scenarios**:

1. **Given** an agent with an end-call tool whose goodbye line is "Thanks, bye!", **When** the
   caller says they are done, **Then** the agent speaks "Thanks, bye!", hangs up, and the call
   records the "agent hangup" reason and a tool-call entry.
2. **Given** a static cold transfer tool to +14155550100, **When** the caller asks for a person
   on a phone call, **Then** the call is handed to that number, the agent leaves, and the call
   records the "call transfer" reason.
3. **Given** a warm transfer tool with a static briefing "Caller needs a refund", **When** the
   transfer is triggered, **Then** the destination hears the briefing (privately or with the
   caller listening, as configured) before the caller is connected, and the caller hears the
   hold message while waiting.
4. **Given** a dynamic transfer tool with routing instructions and an allowed-number list,
   **When** the agent picks a number outside the list, **Then** the transfer is refused, the
   agent is told why, and the call continues.
5. **Given** a transfer or press-digit tool on a browser or WhatsApp call, **When** the agent
   tries to use it, **Then** the agent is told the action is unavailable on this channel and
   the call continues.
6. **Given** a tool named `kb_search` or starting with `route_to_`, **When** the operator saves
   it, **Then** the save is rejected because those names are reserved.
7. **Given** two attached tools with the same name, **When** the operator saves the agent's tool
   set, **Then** the save is rejected and names the clash.
8. **Given** the new-tool dialog, **When** the operator picks the "transfer to a person" preset,
   **Then** the transfer form opens prefilled (name, description, warm handoff) and saving creates
   an ordinary library tool the operator can edit; the preset itself never changes.
9. **Given** a transfer tool request that carries an extra or outdated field next to the
   transfer settings, **When** it is saved, **Then** it is rejected naming the unexpected field,
   so each tool is stored in exactly one shape.

---

### User Story 2 - Call our own systems during a call (Priority: P1)

An operator creates a custom HTTP tool: method, URL, headers (some marked secret), a JSON
Schema describing the parameters the agent must collect, an optional body template, a timeout,
a mapping from response fields to call variables, and a line the agent says if the request is
slow. Before attaching it, they run it from the editor with sample parameters and see the
status, timing, raw response, mapped variables and exactly what the agent would receive.

**Why this priority**: Booking, lookups and CRM updates are the main reason customers deploy
voice agents; this is the extension point for all of them.

**Independent Test**: Create a tool against a test endpoint with one secret header and a
response mapping, run it from the editor, confirm the mapped variables and the masked header
value, attach it to an agent and place a scripted call that triggers it.

**Acceptance Scenarios**:

1. **Given** a tool with a secret header `Authorization: Bearer sk_live_abcd1234`, **When** the
   tool is read back by any user or API client, **Then** the value shows as `****1234` and the
   full value is never returned.
2. **Given** a saved tool with a masked secret, **When** the operator edits only the URL and
   saves, **Then** the secret value is kept unchanged.
3. **Given** parameters `{date: string (required), doctor: string}` and a response mapping
   `next_slot = data.slots[0].time`, **When** the tool runs and the API returns slots, **Then**
   the agent receives `next_slot` and later prompts can use `{{next_slot}}`.
4. **Given** "speak during execution" is on and the API takes 2 seconds, **When** the tool runs,
   **Then** the caller hears the waiting line once, and does not hear it when the API answers
   within 400 ms.
5. **Given** a 3-second timeout and an API that never answers, **When** the tool runs, **Then**
   after 3 seconds the agent is told the request timed out and can recover in conversation; the
   tool-call entry is marked as an error with reason "timeout".
6. **Given** a URL that resolves to a private, loopback or cloud-metadata address, **When** the
   tool runs (from the editor or during a call), **Then** the request is blocked and the reason
   is shown.
7. **Given** a test run from the editor, **When** it completes, **Then** no credit is charged and
   the result shows status code, duration, response body (truncated), mapped variables and the
   payload the agent would see.
8. **Given** the HTTP tool form, **When** the operator types "notaurl" as the URL and leaves the
   field, **Then** the field explains that an absolute https address is needed and Save stays
   disabled; the method list and timeout range are the same as on a flow webhook node.

---

### User Story 3 - Build a knowledge base from documents (Priority: P2)

An operator opens Knowledge, creates a knowledge base (for example "Clinic policies") and
uploads PDF and DOCX files. Each document shows its status (uploaded, processing, ready,
failed with a reason), size, page count and upload date. They can preview the original file,
replace a document with a newer version, and delete documents or whole knowledge bases.

**Why this priority**: Agents that answer policy and product questions need grounded content,
but the core call-control and API tools deliver value first.

**Independent Test**: Upload a 3-page PDF, watch it move to ready, open its preview link, try
the same file again and confirm the duplicate warning, then upload a 25 MB file and a .txt
file and confirm both are rejected with clear messages.

**Acceptance Scenarios**:

1. **Given** a 2 MB PDF with selectable text, **When** it is uploaded, **Then** it shows
   "processing" within 2 seconds and "ready" with page and section counts when done.
2. **Given** a file larger than 20 MB, **When** the operator picks it, **Then** it is rejected
   before upload with "File too large (25.3 MB). The limit is 20 MB."
3. **Given** a file that is not PDF or DOCX (checked by content, not only by extension),
   **When** it is uploaded, **Then** it is rejected with "Only PDF and DOCX files are supported."
4. **Given** a file whose exact content already exists in the same knowledge base, **When** the
   operator picks it, **Then** the upload is refused and the existing document is named; if the
   same content exists in another knowledge base, the operator is warned and may continue.
5. **Given** a document with the same file name but different content, **When** the operator
   chooses "Replace", **Then** the old version keeps serving searches until the new one is
   ready, and is then removed.
6. **Given** a scanned PDF with no extractable text, **When** ingestion runs, **Then** the
   document is marked failed with "No readable text found. Scanned documents are not
   supported yet."
7. **Given** a ready document, **When** the operator clicks Preview, **Then** the original file
   opens through a link that stops working after 10 minutes.
8. **Given** the upload dialog, **When** it opens, **Then** it names the accepted types and the
   20 MB limit, the display name is optional and defaults to the file name, and Upload stays
   disabled until a file is chosen.

---

### User Story 4 - Agents answer from knowledge during calls (Priority: P2)

The operator attaches one or more knowledge bases to an agent. During calls the agent can
search them when a caller asks something the prompt does not cover, and answers from the
passages found. On the knowledge base page the operator can type a question and see which
passages would come back, with their scores and source documents.

**Why this priority**: This is what turns uploaded documents into better answers; it depends
on User Story 3.

**Independent Test**: Attach a ready knowledge base containing a refund policy to an agent,
place a scripted call asking "how long do refunds take?", and confirm the agent searches,
answers with the policy's figure, and the call's tool-call entry lists the passages used.

**Acceptance Scenarios**:

1. **Given** an agent with an attached ready knowledge base, **When** the caller asks a
   question covered by it, **Then** the agent searches, receives at most 4 passages by
   default, and the search result reaches the agent within 300 ms for 95% of searches.
2. **Given** the search does not answer within 800 ms, **When** the limit passes, **Then** the
   agent is told nothing was found and the conversation continues without waiting further.
3. **Given** no passage is relevant enough, **When** the agent searches, **Then** it is told
   "No relevant information found in the knowledge base" instead of receiving weak matches.
4. **Given** the attach dialog, **When** it opens, **Then** knowledge bases are grouped into
   "Ready" and "Not ready", and only those with at least one ready document can be attached.
5. **Given** a knowledge base attached to three agents, **When** the operator deletes it,
   **Then** they are told which agents use it, it is detached from their drafts, and published
   versions that still reference it get no results from it from then on.
6. **Given** the preview box on a knowledge base, **When** the operator searches "refund
   window", **Then** the top passages show with source file, page, section heading and score.
7. **Given** a flow agent, **When** knowledge bases are attached, **Then** every conversational
   node can search them unless that node turns search off (see 004-flow-agents).
8. **Given** the attach dialog with no knowledge base yet, **When** it opens, **Then** it offers
   to create one and upload a PDF or DOCX from the same place, and the empty-state text promises
   only the source types that exist.
9. **Given** the attach dialog, **When** the selection equals what is already attached, **Then**
   Confirm is disabled; confirming a changed selection sends the full new set.

---

### User Story 5 - Use tools safely in simulations (Priority: P3)

Each tool can carry a canned response used when calls are simulated instead of real. Before a
simulation runs, the operator sees which attached tools have no canned response and can fix
them or continue.

**Why this priority**: Simulations (008) need tools that do not hit real systems; this story
only adds the data and checks they rely on.

**Independent Test**: Give an HTTP tool a canned response, run the agent in simulation mode
with a scripted caller, and confirm no network request is made and the canned response
reaches the agent; remove it and confirm the pre-flight check lists the tool.

**Acceptance Scenarios**:

1. **Given** an HTTP tool with canned response `{"slots":["10:00"]}`, **When** it runs in a
   simulated call, **Then** no request is sent, the canned text is returned as the response
   (response mapping still applies) and the tool-call entry is marked as mocked.
2. **Given** a transfer or press-digit tool in a simulated call, **When** it runs, **Then** it
   reports success without touching telephony.
3. **Given** an agent with two HTTP tools and one has no canned response, **When** the operator
   checks simulation readiness, **Then** that one tool is listed by name.
4. **Given** end-call, transfer and press-digit tools, **When** the operator edits them, **Then**
   no canned-response field is shown, they never appear as missing in the readiness check, and in
   simulations they report the fixed outcome for their type.

---

### Edge Cases

- Tool edited after an agent version was published: published versions keep the tool as it
  was when published; only the draft and the next published version see the change.
- Tool deleted while attached: the operator is told which agents use it; deletion detaches it
  from drafts and does not affect published versions or live calls.
- Agent calls a tool with arguments that do not match the parameter schema: the request is not
  sent; the agent gets a validation error naming the field and can ask the caller again.
- HTTP response larger than 64 KB: the read is cut off and treated as an error "response too
  large".
- Response mapping path missing in the response: that variable is left unset, the others are
  still mapped, and the tool-call entry lists the missing path.
- URL or body uses a `{{variable}}` with no value: the URL case fails before sending with
  "missing variable"; in the body the placeholder becomes an empty string and is flagged.
- Transfer destination busy or not answering within the ring timeout: the agent is told the
  transfer failed and the caller stays with the agent.
- Press digit called twice inside the cooldown window: the second press is delayed until the
  cooldown ends rather than dropped.
- Upload interrupted or the browser closed mid-upload: no document row is left behind.
- Ingestion worker crashes mid-document: the job is retried and produces each passage once.
- Embedding provider unavailable: ingestion retries up to 3 times with backoff, then the
  document is marked failed with a retry button.
- Two documents in a workspace exceed the storage quota: the upload is refused with the quota
  and current usage.
- Knowledge base with documents still processing is attached: only ready documents are
  searched; the others join automatically when ready.
- A caller tries to make the agent reveal tool secrets or internal URLs: secrets are never in
  the agent's context, so they cannot be spoken.

## Requirements *(mandatory)*

### Functional Requirements

**Tool library**

- **FR-001**: System MUST keep tools in a per-workspace library, each with a type (end call,
  transfer call, press digit, HTTP request), a name, a description, type-specific settings and,
  for HTTP tools, an optional canned response for simulations (FR-044).
- **FR-002**: Tool names MUST start with a lowercase letter, contain only lowercase letters,
  digits and underscores, be at most 64 characters, and not be `kb_search` or start with
  `route_to_`. Descriptions are required (1 to 1,000 characters).
- **FR-003**: Users MUST be able to create, list (with type filter and search), view, edit,
  duplicate and delete tools. The tool type cannot be changed after creation.
- **FR-004**: System MUST show, for each tool, which agents use it (drafts and published
  versions currently serving calls).
- **FR-005**: Users MUST be able to attach and detach tools to an agent as a set; names MUST be
  unique within the set and an agent MAY have at most 25 tools.
- **FR-006**: Flow agents MUST be able to attach library tools to individual conversational
  nodes; node-level attachment is specified in 004-flow-agents and uses the same tool library
  and validation.
- **FR-007**: Publishing an agent version MUST capture the full definition of every attached
  tool (with secret values replaced by references), so later tool edits never change a
  published version.

**Call-control tools**

- **FR-008**: The end-call tool MUST optionally speak a goodbye line, then end the call with
  the "agent hangup" reason.
- **FR-009**: The transfer tool MUST support static routing (one fixed number in international
  E.164 format) and dynamic routing (the agent chooses the number guided by routing
  instructions), with an optional list of allowed numbers that a dynamic choice must match.
- **FR-010**: The transfer tool MUST support cold handoff (caller is handed over directly) and
  warm handoff (the destination is briefed first, privately or with the caller listening, using
  a fixed briefing or one the agent writes from instructions), a hold message for the caller,
  and a ring timeout (default 30 seconds).
- **FR-011**: A successful transfer MUST end the agent's part of the call with the "call
  transfer" reason; a failed transfer MUST return the failure to the agent and keep the call.
- **FR-012**: The press-digit tool MUST send keypad tones (digits 0 to 9, `*`, `#`, up to 20 per
  press) after a configurable delay (default 1,000 ms) and enforce a minimum gap between
  presses (default 5,000 ms).
- **FR-013**: Transfer and press-digit tools MUST only act on phone calls; on browser and
  WhatsApp calls they MUST return an "unavailable on this channel" result to the agent.

**HTTP tools**

- **FR-014**: The HTTP tool MUST let users set method (GET, POST, PUT, PATCH, DELETE; default
  POST), URL, headers, an optional body template, a parameter schema (JSON Schema object), a
  timeout (default 8 seconds, 1 to 30 seconds), response mappings and an optional waiting line.
- **FR-015**: URL, header values and body template MUST support `{{name}}` placeholders filled
  from the agent's arguments, then call variables, then previously mapped variables.
- **FR-016**: When no body template is set, the agent's arguments MUST be sent as the JSON body
  for POST, PUT and PATCH, and as query parameters for GET and DELETE.
- **FR-017**: Arguments MUST be validated against the parameter schema before any request is
  sent.
- **FR-018**: Response mappings MUST copy values found at dot paths (for example
  `data.slots[0].time`) into named call variables usable by later prompts and flow nodes.
- **FR-019**: The agent MUST receive the mapped variables when mappings exist, otherwise the
  response body cut to 4,000 characters, plus the status code.
- **FR-020**: When the waiting line is enabled and the request has not finished within 400 ms,
  the agent MUST speak it once while waiting.
- **FR-021**: System MUST refuse requests whose target resolves to private, loopback,
  link-local or cloud-metadata addresses, MUST require HTTPS outside development environments,
  MUST not follow redirects to refused targets, and MUST cap response size at 64 KB.
- **FR-022**: System MUST NOT retry HTTP tool requests automatically (to avoid duplicate side
  effects on the customer's systems).
- **FR-023**: Users MUST be able to test-run an HTTP tool (saved or unsaved) from the editor
  with sample arguments and variables, free of charge, limited to 30 runs per minute per
  workspace.

**Secrets**

- **FR-024**: Header values marked secret MUST be stored encrypted and MUST only ever be
  returned masked (`****` plus the last 4 characters).
- **FR-025**: Editing a tool without supplying a new secret value MUST keep the stored secret.
- **FR-026**: Secret values MUST NOT appear in agent context, transcripts, tool-call entries,
  logs, traces or version snapshots.

**Tool execution records**

- **FR-027**: Every tool invocation during a call MUST be recorded with tool name and type,
  arguments, output (cut to 4 KB), error flag and error code, duration, turn number and whether
  the result was mocked.
- **FR-028**: Tool execution overhead added by the platform (excluding the customer API's own
  response time) MUST stay at or below 50 ms at the 95th percentile.

**Knowledge bases**

- **FR-029**: Users MUST be able to create, rename, describe, list and delete knowledge bases,
  each holding many documents.
- **FR-030**: System MUST accept PDF and DOCX uploads up to 20 MB, checked by file content, and
  reject others with the messages in User Story 3.
- **FR-031**: System MUST detect duplicates by exact content within the workspace before the
  file is sent: same content in the same knowledge base is refused; same content elsewhere and
  same file name with different content produce a warning, with a "Replace" option for the
  latter.
- **FR-032**: System MUST process documents in the background (extract text, split into
  passages, index for meaning-based search) and show status `uploaded`, `processing`, `ready`
  or `failed` with a readable reason and a retry action.
- **FR-033**: System MUST give a document preview link that expires after 10 minutes.
- **FR-034**: Deleting a document MUST remove its passages from search immediately; deleting a
  knowledge base MUST list the agents using it, detach it from their drafts, and remove its
  documents and passages.
- **FR-035**: Users MUST be able to attach and detach knowledge bases to an agent (at most 10
  per agent); only knowledge bases with at least one ready document are attachable.
- **FR-036**: When an agent version has knowledge bases, the agent MUST be able to search them
  during calls by asking a question in natural language.
- **FR-037**: A search MUST return at most 4 passages by default (up to 8 when configured)
  above a relevance threshold, each with source document, page, section heading and score,
  limited to 4,000 characters in total.
- **FR-038**: A search MUST deliver results to the agent within 300 ms for 95% of searches and
  MUST give up after 800 ms with an empty result so the call never stalls on retrieval.
- **FR-039**: Users MUST be able to run the same search from the knowledge base page to preview
  results.
- **FR-040**: Document processing cost MUST be recorded as a "knowledge ingestion" feature
  charge visible in usage reporting (001).

**Simulations**

- **FR-041**: HTTP tools MUST carry an optional canned response; in simulated calls HTTP tools
  MUST return it without sending a request, and end-call, transfer and press-digit tools MUST
  report their fixed outcome without touching telephony.
- **FR-042**: System MUST list, per agent, the attached HTTP tools (and flow webhook nodes, 004)
  that lack a canned response.

**Live UI walkthrough additions (2026-10-16)**

- **FR-043**: The new-tool dialog MUST offer platform presets that prefill the form: end call
  with a goodbye line, transfer to a person (warm), press digit for phone menus and an HTTP
  example with a parameter schema. Saving creates an ordinary library tool; presets are
  read-only and are stored in the current tool shape.
- **FR-044**: The canned-response field MUST be shown only for HTTP tools. End-call, transfer and
  press-digit tools MUST have fixed simulated outcomes (call ends; transfer succeeds; digits are
  accepted) and MUST NOT count as missing in the readiness check.
- **FR-045**: Each tool type MUST have exactly one stored shape; create and update requests with
  unknown or outdated fields MUST be rejected naming the field, never stored alongside the
  current ones.
- **FR-046**: The tool editor MUST check fields as they are edited (absolute https URL, E.164
  numbers, JSON Schema syntax, required fields named in the message) and keep Save disabled
  while any is invalid. HTTP tools and flow webhook nodes MUST offer the same methods (GET, POST,
  PUT, PATCH, DELETE), timeout range and options.
- **FR-047**: The knowledge attach dialog MUST offer search, the Ready and Not ready groups, and a
  shortcut to create a knowledge base and upload a document without leaving the agent. Its
  empty-state text MUST promise only the source types that exist (PDF and DOCX in v1). Confirm
  MUST be disabled while the selection equals the attached set.
- **FR-048**: The upload dialog MUST name the accepted types and the size limit, take an optional
  display name that defaults to the file name, and keep Upload disabled until a file is chosen.
  It MUST be reachable from the page header and from the empty state.

### Key Entities

- **Tool**: a reusable action in the workspace library; name, description, type, type-specific
  settings, optional canned response (HTTP tools only), timestamps.
- **HTTP Request Settings**: method, URL, headers (some secret), body template, timeout,
  response mappings, waiting line; shared with flow webhook nodes (004).
- **Transfer Settings**: routing type, number or routing instructions, allowed numbers, cold or
  warm, warm briefing settings, hold message, ring timeout; shared with flow transfer nodes.
- **Secret Reference**: pointer from a tool header to an encrypted stored value; only the last
  4 characters are ever shown.
- **Tool Call Record**: one invocation during a call, stored with the call's events.
- **Knowledge Base**: named collection of documents in a workspace; attachable to agents.
- **Document**: one uploaded file in a knowledge base; name, type, size, content fingerprint,
  status, failure reason, page and passage counts.
- **Passage**: a searchable piece of a document with its position (page, heading).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can create, test-run and attach an HTTP tool in under 5 minutes the
  first time.
- **SC-002**: 95% of knowledge searches during calls return to the agent within 300 ms and none
  hold the conversation longer than 800 ms.
- **SC-003**: Platform overhead per tool call stays at or below 50 ms at the 95th percentile, and
  agents with tools show no regression in turn latency on the benchmark call set.
- **SC-004**: A 20 MB text PDF is searchable within 2 minutes of upload completing.
- **SC-005**: Zero full secret values are found in API responses, transcripts, call events,
  logs or version snapshots in an automated scan of the test suite output.
- **SC-006**: 100% of requests to blocked address ranges in the security test set are refused.
- **SC-007**: On a labelled set of 50 questions answerable from a reference document, the
  correct passage is in the returned passages for at least 85% of questions.
- **SC-008**: 100% of tool invocations in test calls appear in the call's records with duration
  and outcome.

## Assumptions

- Phone transfers and keypad tones apply to phone calls handled by the voice runtime (003) and
  numbers set up in channels (010); browser and WhatsApp calls cannot transfer in v1.
- Customers' HTTP APIs are reachable from the public internet; private network connectivity is
  out of scope.
- Scanned (image-only) PDFs need OCR, which is out of scope for v1; Markdown, plain text and URL
  sources are later additions.
- Search configuration (passage size, overlap, model) is fixed by the platform in v1 and not
  shown to operators.
- Each workspace may store up to 1 GB of documents and 200 documents per knowledge base in v1;
  limits are configurable per environment.
- Knowledge search during calls is not billed separately in v1; its small cost is covered by the
  platform fee and recorded as a usage meter for later pricing.
- Agent drafts, publishing and version snapshots come from 002-agent-builder; call events and
  the per-call event stream come from 003-voice-runtime; simulations that consume canned
  responses come from 008-testing-simulation.
- Tool name suggestions (`end_call`, `transfer_call`, `press_digit`, `check_availability`)
  are shown as placeholders only.
- Press-digit tools have no separate on/off switch; attaching or detaching the tool decides
  whether the agent can press digits.
- Post-call analysis variables are owned by 007-quality-evals, even where their editor appears
  inside agent or flow settings.
