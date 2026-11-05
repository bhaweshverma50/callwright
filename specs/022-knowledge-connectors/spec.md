# Feature Specification: Knowledge connectors and integrations (022)

**Feature Branch**: `022-knowledge-connectors`
**Created**: 2026-11-05
**Status**: Draft
**Input**: Keep knowledge bases in step with the documents a business already maintains, starting
with Google Drive. Sync safely: follow changes, skip unchanged files, never delete on lost access,
never archive a large share at once, keep a run history, and never reach the source during calls.
Add a shared Connections page for OAuth and service-account credentials with health and circuit
breakers, used by tools and knowledge alike. Let agents use MCP tools through the platform, with
an admin approving each tool. Give every knowledge document a summary card.

## Why

Today a knowledge base holds only files someone uploads: PDF and DOCX up to 20 MB, deduplicated by
content, processed in the background (005). Callwright has no other way in:

- When a policy document changes in the business's shared drive, someone has to notice, download
  it and use Replace. Knowledge bases drift out of date without anyone seeing it.
- Credentials live on each HTTP tool as encrypted secret headers (005 FR-024). The same API key is
  pasted into several tools, there is no OAuth, and nothing shows that a key has expired until
  calls start failing.
- When a customer system is down, every call that uses its tools waits out the full timeout
  (8 seconds by default) before the agent hears it failed.
- Many systems now publish their actions as MCP servers. Using one today means hand-writing an HTTP
  tool for each action.
- A ready document shows its page and passage counts but nothing about what it says. Operators
  cannot tell at a glance whether the right content made it in.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sync a knowledge base from Google Drive (Priority: P1)

An operator adds a **Google Drive source** to a knowledge base: they pick a connection
(Story 2), then a folder or shared drive. The first sync imports every supported file (Google
Docs, PDF and DOCX within the 20 MB limit). After that the platform follows Drive's change feed,
by default every 15 minutes, and on "Sync now". Each sync re-processes only files whose content
changed, recognised by content hash. Files removed from the folder are archived: they leave
search but can be restored. Calls always search Callwright's synced copy and never query Drive
while a caller is waiting.

**Why this priority**: Up-to-date knowledge is the most requested integration, and stale policy
answers are a real risk for operators.

**Independent Test**: Connect a folder with 10 documents and wait for the first sync. Edit one,
rename one, delete one and add one. Run Sync now and confirm the run shows 1 updated, 1 renamed
with no re-processing, 1 archived, 1 added and 7 unchanged, and that search reflects all four
changes.

**Acceptance Scenarios**:

1. **Given** a folder with 12 Google Docs, PDFs and DOCX files, **When** the source is added,
   **Then** all supported files are imported, each document shows "from Google Drive" with a link
   to the original, and unsupported files are listed as skipped with the reason.
2. **Given** a synced file whose content has not changed but whose name or modified time has,
   **When** a sync runs, **Then** it is not re-processed, and its name is updated.
3. **Given** a synced file that was edited, **When** a sync runs, **Then** the old version keeps
   serving search until the new one is ready, as with Replace (005).
4. **Given** a file removed from the folder, **When** a sync runs, **Then** its document is
   archived, it leaves search, and it can be restored for 30 days.
5. **Given** a sync would archive 25% of the source's documents, **When** it runs, **Then** it
   archives none of them, imports and updates the rest, marks the source "needs attention" with
   "This sync would archive 25 of 100 documents", and waits for the owner to confirm or cancel the
   archiving.
6. **Given** the connection loses access to the folder, **When** a sync runs, **Then** no document
   is archived or deleted, existing documents keep serving search, and the source shows "needs
   attention: access lost" with a reconnect action.
7. **Given** a knowledge base with a Drive source, **When** a call searches it while Drive is
   unreachable, **Then** the search returns from the synced copy, and the call is unaffected.
8. **Given** any source, **When** the operator opens its sync history, **Then** each run shows
   start, end, trigger (first, scheduled, change, manual), counts of added, updated, unchanged,
   renamed, archived, skipped and failed files, and the errors.

---

### User Story 2 - Manage credentials once on a Connections page (Priority: P1)

A workspace **Connections** page lists every connection to an outside system. A connection is either
an **OAuth** connection (the owner signs in to Google, for example, and grants access) or a
**service account** (a key the owner uploads). Simpler connections hold an API key or bearer token.
Each connection shows its health: healthy, expiring soon, failing or revoked, with its last
successful use. HTTP tools, knowledge sources and MCP servers pick a connection instead of carrying
their own secret. A connection that keeps failing trips a **breaker**, so calls fail fast with the
tool's failure line instead of waiting out the timeout.

**Why this priority**: Drive sync needs it, and it removes the most common silent failure: an
expired key that nobody sees until callers complain.

**Independent Test**: Create an API-key connection and use it from two HTTP tools. Rotate the key
once and confirm both tools use the new key on their next request. Point the connection at an
endpoint that returns 503 and confirm the breaker opens after the third failure, later calls fail
in under 100 ms, and the breaker closes again after the cool-down.

**Acceptance Scenarios**:

1. **Given** the owner adds a Google OAuth connection, **When** they approve access, **Then** the
   connection shows the account it acts as, the access granted, and "healthy".
2. **Given** a connection used by 3 tools and 1 knowledge source, **When** its page is opened,
   **Then** all four users of it are listed.
3. **Given** a connection secret, **When** it is read back by anyone, **Then** only the last
   4 characters are shown (005 FR-024).
4. **Given** the owner replaces a connection's key, **When** the next request is made, **Then** it
   uses the new key, and no tool or source needs editing.
5. **Given** a connection whose OAuth access was revoked, **When** it is next used, **Then** it
   shows "revoked", a critical item appears in Needs attention (018), and sync sources using it
   pause without deleting anything.
6. **Given** 3 failures within 30 seconds from overload or temporary errors, **When** the next
   request is due, **Then** the breaker is open, the request is not sent, and the tool returns its
   failure at once, for 20 seconds after an overload or 15 seconds after other temporary errors.
7. **Given** an authentication failure, **When** it happens, **Then** the breaker opens for
   15 minutes or until the owner fixes the connection and runs Test, whichever comes first.
8. **Given** an existing HTTP tool with secret headers, **When** the operator chooses "Move to a
   connection", **Then** the secret becomes a connection, and the tool uses it with no change in
   behaviour.

---

### User Story 3 - Use MCP tools, approved one by one (Priority: P2)

The owner adds an **MCP server** by URL and connection. The platform asks the server for its list
of tools and keeps a **snapshot** of each tool's name, description and parameters. Every tool
starts as pending. The owner approves the ones they want and sets each one's effect (read, write,
send or destructive, 016). Approved tools appear in the tool library and attach to agents like
any other tool. A scheduled re-list, daily by default, compares the server's current list with the
snapshot. New, changed and removed tools are flagged for review and never turned on by
themselves.

**Why this priority**: It opens up many systems at once, but it depends on Connections and on safe
tool actions (016), and hand-built HTTP tools already cover the urgent cases.

**Independent Test**: Add a test MCP server with 3 tools. Approve 2, setting one as read and one as
write. Attach them to an agent and confirm a call uses them through the platform. Change one
tool's description on the server, run the re-list and confirm the change is flagged while calls
keep using the approved description.

**Acceptance Scenarios**:

1. **Given** a newly added MCP server, **When** its tools are listed, **Then** each shows its name,
   description and parameters as pending, and none can be attached yet.
2. **Given** a pending tool, **When** the owner approves it, **Then** they must set its effect, and
   the tool joins the library with that effect and the snapshot's description and parameters.
3. **Given** an approved tool whose description or parameters changed on the server, **When** the
   re-list runs, **Then** the tool keeps working with its approved snapshot, shows "changed on
   server: review", and the owner can see the difference and approve or reject it.
4. **Given** a new tool appears on the server, **When** the re-list runs, **Then** it is added as
   pending and is never offered to agents until approved.
5. **Given** an approved tool removed from the server, **When** the re-list runs, **Then** it is
   marked unavailable, calls get its failure line, and a Needs attention item names the agents
   using it.
6. **Given** an MCP tool call during a call, **When** it runs, **Then** confirmation, the action
   ledger, idempotency keys, per-turn caps and untrusted-output handling (016) apply as for HTTP
   tools, and the platform, not the agent, talks to the server.

---

### User Story 4 - A summary card for every knowledge document (Priority: P3)

When a document becomes ready, whether uploaded or synced, the platform extracts a **summary card**:
a short summary, the main topics, key figures and dates (each with the page and a verbatim quote),
and policy statements (what is allowed, required or not allowed). The card shows on the document
and as a coverage hint in the knowledge attach dialog. The operator can mark a card item wrong,
which hides it.

**Why this priority**: It helps operators check what an agent knows, but agents already answer
from the passages without it.

**Independent Test**: Upload a refund policy. Confirm the card lists the refund window with the
page and exact sentence it came from. Change the document through Drive and confirm the card is
regenerated.

**Acceptance Scenarios**:

1. **Given** a ready document, **When** the operator opens it, **Then** the card shows a summary
   of at most 80 words, up to 8 topics, key figures and dates, and policy statements.
2. **Given** a figure or policy on the card, **When** it is shown, **Then** it carries the page and
   a verbatim quote from the document. Items with no supporting quote are not shown.
3. **Given** the document's content changes, **When** the new version becomes ready, **Then** the
   card is regenerated, and items the operator hid stay hidden if the same item reappears.
4. **Given** the attach dialog, **When** knowledge bases are listed, **Then** each shows the topics
   from its documents' cards.
5. **Given** card extraction fails, **When** the document is otherwise ready, **Then** the
   document still serves search, and the card shows "Summary unavailable" with a retry action.

### Edge Cases

- A file shared into the folder from outside the organisation: imported like any other if the
  connection can read it.
- A file moved between two folders that are both sources of the same knowledge base: treated as
  a move, not a delete and an add.
- The same file in two knowledge bases through two sources: processed once for each knowledge
  base, and each knowledge base deduplicates within itself (005).
- A synced file over 20 MB, a scanned PDF or an unsupported type: skipped or failed with the 005
  reason, and listed in the run.
- A sync running when the next scheduled one is due: the next one is skipped, never run twice at
  once.
- A source with fewer than 10 documents: the 20% rule would block even one removal, so up to 2
  archivals are always allowed.
- The owner cancels the archiving the 20% rule held back: those documents stay in search, and the
  next sync checks them again.
- Deleting a connection in use: refused while any tool, source or MCP server uses it, and the
  users are listed.
- A service-account key that has been in use for over 90 days: a warning suggests rotating it.
- An MCP server that is unreachable during the re-list: the snapshot is unchanged, and the run is
  recorded as failed.
- An MCP tool whose parameters are not a JSON object schema: cannot be approved, with the reason
  shown.
- An MCP tool returning content too large: cut off as for HTTP tools (64 KB), and the tool call is
  treated as an error.
- Simulations (008): MCP tools use their canned responses, as HTTP tools do. Knowledge sources are
  searched for real.

## Requirements *(mandatory)*

### Functional Requirements

**Knowledge sources (Google Drive)**

- **FR-001**: A knowledge base MUST accept, alongside uploads, one or more Google Drive sources,
  each a folder (optionally with subfolders) or a shared drive, read through a connection.
- **FR-002**: The first sync MUST import every supported file: Google Docs (as text), PDF and DOCX
  within the 20 MB limit. Other files MUST be listed as skipped with the reason.
- **FR-003**: After the first sync, the platform MUST follow the source's change feed every
  15 minutes by default (adjustable from 5 minutes to 24 hours) and on "Sync now".
- **FR-004**: A changed file MUST be re-processed only when its content hash differs from the
  synced copy. Name and location changes MUST update metadata without re-processing.
- **FR-005**: An updated file's previous version MUST keep serving search until the new version is
  ready.
- **FR-006**: A file removed from the source MUST be archived, not deleted: removed from search,
  restorable for 30 days, then deleted.
- **FR-007**: A single sync MUST NOT archive more than 20% of a source's documents, with at least
  2 always allowed. If more would be archived, the sync MUST archive none, complete the other
  changes, mark the source "needs attention" and wait for the owner to confirm or cancel.
- **FR-008**: When access to a source or its connection is lost, the sync MUST change nothing,
  documents MUST keep serving search, and the source MUST show "needs attention: access lost" with
  a reconnect action.
- **FR-009**: Each sync run MUST be recorded with start and end times, trigger, counts (added,
  updated, unchanged, renamed, archived, held back, skipped, failed) and errors per file. History
  MUST be kept for 90 days.
- **FR-010**: Searches during calls MUST use only Callwright's synced copy. No call MUST wait on a
  connected source.
- **FR-011**: Synced documents MUST show their origin and a link to the original, and MUST NOT be
  editable or replaceable by upload while the source is connected.
- **FR-012**: Removing a source MUST offer to keep its documents as uploads or archive them.

**Connections**

- **FR-013**: The workspace MUST have a Connections page listing connections of these kinds:
  OAuth (Google in v1), service account (Google in v1), API key and bearer token. Each shows its
  kind, the account or scope it acts as, health, last successful use, expiry if known, and its
  users.
- **FR-014**: Connection secrets MUST be stored encrypted, shown only masked, and never placed in
  agent context, transcripts, logs or version snapshots (005 FR-026).
- **FR-015**: HTTP tools, knowledge sources and MCP servers MUST be able to use a connection
  instead of their own secrets. Replacing a connection's credentials MUST take effect on the next
  request, with no edit to its users.
- **FR-016**: Each connection MUST have a Test action. Health MUST be one of healthy, expiring
  (within 7 days), failing or revoked, updated from real use and from tests.
- **FR-017**: Each connection MUST have a circuit breaker. After 3 temporary failures within
  30 seconds it MUST open for 15 seconds. On an overload response (rate limited or unavailable) it
  MUST open for 20 seconds. On an authentication failure it MUST open for 15 minutes, or until a
  successful Test. Repeated openings MAY extend the time, up to 30 minutes.
- **FR-018**: While a breaker is open, requests through that connection MUST NOT be sent. Tools
  MUST return their failure at once (with their failure line, 016). Syncs MUST wait.
- **FR-019**: Failing, revoked and soon-expiring connections MUST appear in Needs attention (018).
- **FR-020**: An HTTP tool's secret headers MUST be convertible into a connection in one action
  without changing what the tool sends.
- **FR-021**: A connection in use MUST NOT be deletable.

**MCP tools**

- **FR-022**: The owner MUST be able to add a remote MCP server by URL with an optional
  connection. The platform MUST connect to the server itself. Agents never connect directly.
- **FR-023**: On adding a server, and on each re-list, the platform MUST fetch the server's tool
  list and keep a snapshot of each tool's name, description and parameters.
- **FR-024**: Each tool MUST start as pending. The owner MUST approve it before it can be attached,
  and MUST set its effect (016) when approving. Tool names MUST be made unique in the library and
  follow 005's naming rules.
- **FR-025**: The agent MUST only ever see the approved snapshot's description and parameters,
  never the server's live versions.
- **FR-026**: A scheduled re-list (daily by default, and on demand) MUST compare the server's list
  with the snapshots. New tools MUST be added as pending. Changed tools MUST keep their approved
  snapshot, be flagged "changed on server: review" with the difference, and change only on the
  owner's approval. Removed tools MUST be marked unavailable. Nothing MUST be enabled or changed
  without approval.
- **FR-027**: MCP tool calls MUST go through the same execution path as HTTP tools: timeouts,
  confirmation, ledger, idempotency keys, caps, untrusted output and parameter bindings (016),
  size limits and the tool-call record (005 FR-027).
- **FR-028**: MCP tools MUST support canned responses for simulations (005 FR-041).

**Document summary cards**

- **FR-029**: When a document becomes ready, the platform MUST extract a summary card: a summary of
  at most 80 words, up to 8 topics, key figures and dates, and policy statements (allowed,
  required, not allowed).
- **FR-030**: Every figure, date and policy statement on the card MUST carry its page and a
  verbatim quote from the document. Items without one MUST be dropped.
- **FR-031**: Cards MUST be regenerated when the document's content changes. Operators MUST be
  able to hide a card item, and hidden items MUST stay hidden when they reappear unchanged.
- **FR-032**: Card extraction failing MUST NOT stop the document serving search. The card MUST
  offer a retry.
- **FR-033**: The knowledge attach dialog MUST show each knowledge base's topics, taken from its
  cards.
- **FR-034**: Sync processing and card extraction MUST be billed as knowledge ingestion charges
  (005 FR-040).

**General**

- **FR-035**: Connections, sources, sync runs, MCP servers, snapshots and cards MUST be tenant data
  under the workspace's isolation rules.
- **FR-036**: Adding, approving, rejecting and changing connections, sources and MCP tools MUST be
  recorded in the audit history (018).

### Key Entities

- **Connection**: credentials for one outside system. It has a kind (OAuth, service account, API
  key, bearer token), the identity it acts as, health, expiry, breaker state and its users.
- **Knowledge source**: a Drive folder or shared drive feeding one knowledge base through a
  connection. It holds the sync schedule, last change position and state (syncing, healthy, needs
  attention).
- **Sync run**: one sync of a source, with its trigger, times, counts and per-file errors.
- **Synced document**: a knowledge document with its origin file, content hash and archive state.
- **MCP server**: a remote MCP endpoint with an optional connection and a re-list schedule.
- **MCP tool snapshot**: the approved name, description and parameters of one server tool, with its
  status (pending, approved, changed on server, rejected, unavailable) and effect.
- **Summary card**: the extracted summary, topics, figures, dates and policy statements of one
  document version, each with a page and quote, plus hidden items.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A change to a Drive file is searchable in calls within 20 minutes at the default
  schedule, and within 5 minutes of Sync now for a file up to 20 MB.
- **SC-002**: A re-sync of 200 unchanged files re-processes none of them and finishes in under
  2 minutes.
- **SC-003**: In fault tests (access revoked, folder emptied, 50% of files removed), zero documents
  are deleted, and no more than 20% of any source is archived in one sync.
- **SC-004**: Calls make zero requests to Drive. Knowledge search latency is unchanged (005
  SC-002).
- **SC-005**: With a connection's breaker open, tools using it return a failure in under 100 ms in
  95% of attempts.
- **SC-006**: Over 30 days of scheduled re-lists against a server whose tools change, zero tools
  are enabled or changed without the owner's approval.
- **SC-007**: On a set of 20 policy documents, at least 90% of card figures match their quoted
  source exactly. No figure appears without a quote.
- **SC-008**: An operator connects a Drive folder and has a searchable knowledge base in under
  10 minutes the first time.

## Assumptions

- Google Drive is the only knowledge source in v1. Other sources (SharePoint,
  wikis, websites) can follow later.
- Google Docs are read as text. Google Sheets and Slides are skipped in v1.
- One user owns each workspace in v1 (001), so "owner" and "admin" mean that user. OAuth access is
  granted by that user's Google account, or by a service account the owner creates.
- MCP servers are remote and reachable over HTTPS from the public internet. Local or private
  servers are out of scope, as they are for HTTP tools (005).
- Breaker timings are platform defaults that operators cannot change in v1.
- Needs attention and audit history are defined in 018. Tool effects, confirmation, the ledger and
  parameter bindings are defined in 016.
- Builds on 005 (tools and knowledge), 008 (simulations) and 018 (Needs attention, audit).

## Out of scope

- Querying any source live during a call.
- Two-way sync, or writing back to Drive.
- Sources other than Google Drive, and OAuth providers other than Google.
- Per-document access rules (showing different documents to different callers).
- Using summary-card policy statements to drive approvals or QA checks automatically. That is
  later work alongside live approvals (020).
- Hosting MCP servers, or exposing Callwright itself as an MCP server.
