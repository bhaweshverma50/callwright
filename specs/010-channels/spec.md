# Feature Specification: Channels (Phone Numbers, Outbound Calls, WhatsApp)

**Feature Branch**: `010-channels`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Bring-your-own SIP trunk number import (number, label, termination address, optional credentials); inbound and outbound agent attachment per number; inbound routing and outbound trunks on the media platform; an outbound call API (destination, from number, agent, dynamic variables, idempotency); WhatsApp Business voice channels (credentials, webhook verification, attach agent, caller routes mapping caller numbers to agents); number edit and delete that never drops an active call."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import a number and let an agent answer it (Priority: P1)

An operator already has phone numbers with a carrier. On the Channels page they click "Import
number", enter the number, a label ("Main Office Line"), the carrier's termination address and,
if the carrier requires it, a username and password. Callwright shows the address to paste into
the carrier's origination settings. The operator picks an inbound agent for the number. When
someone dials the number, the agent answers after the configured ring time, and the call shows
in call history with the caller's number, the number dialled and the agent version used.

**Why this priority**: Inbound phone calls are the most common production use and the reason
most operators sign up. Nothing on a phone works without an imported number.

**Independent Test**: Import a number against a test carrier (or a SIP test client), attach a
published agent, dial the number, and confirm the agent greets the caller and the call record
has channel "phone inbound", correct from and to numbers, and the number's identifier.

**Acceptance Scenarios**:

1. **Given** the import form, **When** the operator enters `+14155550100`, label "Main Office
   Line" and termination address `trunk.example-carrier.com:5060`, **Then** the number is saved,
   becomes active within 30 seconds, and the page shows the origination address to configure at
   the carrier.
2. **Given** the termination address `sip:trunk.example-carrier.com`, **When** the form is
   submitted, **Then** the scheme prefix is removed and the address saved as
   `trunk.example-carrier.com`.
3. **Given** a number already imported in any workspace, **When** another import of the same
   number is attempted, **Then** it is refused with "This number is already registered" and no
   detail about the other workspace.
4. **Given** an active number with no inbound agent, **When** someone dials it, **Then** the call
   is declined before any agent joins, no call is charged and no call record is created.
5. **Given** an active number with a published inbound agent, **When** someone dials it, **Then**
   the caller hears ringing for the agent's ring duration, then the agent's greeting, and the
   call record shows the caller's number as "from" and the imported number as "to".
6. **Given** an inbound agent with no published version, **When** the operator tries to attach
   it, **Then** the attachment is refused with "Publish this agent before attaching it to a
   number".
7. **Given** the media platform is unreachable during import, **When** the import completes,
   **Then** the number is saved with status "error" and a reason, and a "Retry setup" action
   makes it active once the platform is reachable.

---

### User Story 2 - Place outbound calls from a number (Priority: P1)

An operator attaches an outbound agent to a number. From the number's panel they click "Make
outbound call", enter the destination, fill the agent's variables (pre-filled with defaults)
and start the call. Developers do the same through the API with a destination, the from number,
an optional agent, variables, metadata and an idempotency key. The call rings the destination;
the outcome (answered, busy, no answer, failed) is recorded and sent to the agent's webhook.

**Why this priority**: Outbound calling (reminders, follow-ups, qualification) is the second
core use case and the main driver of call volume.

**Independent Test**: Request an outbound call to a test destination that answers; confirm the
agent speaks after answer and the call record has channel "phone outbound". Repeat the same
request with the same idempotency key and confirm no second call is placed.

**Acceptance Scenarios**:

1. **Given** a number with an outbound agent, **When** an outbound call is requested to
   `+14155550199`, **Then** the request returns a call identifier within 1 second and the
   destination starts ringing within 2 seconds.
2. **Given** a request without an agent, **When** the from number has no outbound agent,
   **Then** it is refused with "This number has no outbound agent; pass agent_id or attach one".
3. **Given** the same request body and idempotency key sent twice, **When** both arrive,
   **Then** exactly one call is placed and both responses return the same call identifier.
4. **Given** the same idempotency key with a different body, **When** it arrives, **Then** it is
   refused as a key reuse.
5. **Given** a destination that is busy, **When** the call is placed, **Then** the call ends with
   status "busy", is not charged, and `call_ended` is sent.
6. **Given** a destination that does not answer within the ring timeout (default 30 seconds),
   **When** the timeout passes, **Then** the call ends with status "no answer".
7. **Given** a workspace at its concurrency limit or without credit, **When** an outbound call
   is requested, **Then** it is refused with the same reasons as any other call.
8. **Given** the destination equals the from number, **When** requested, **Then** it is refused.

---

### User Story 3 - Edit and remove numbers without dropping calls (Priority: P2)

An operator changes a number's label, termination address, transport, credentials, allowed
source addresses, agents or inbound webhook. Credentials are never shown again after saving;
leaving the password empty keeps the current one. Changing or detaching an agent affects only
new calls. Deleting a number with calls in progress offers "Delete when idle": the number stops
taking new calls at once and is removed after the last active call ends.

**Why this priority**: Operators reconfigure numbers often; dropping a live customer call
during an edit is unacceptable, but the first two stories deliver value without editing.

**Independent Test**: With one active call on a number, change its inbound agent and delete it
with "Delete when idle"; confirm the active call continues to its natural end, new calls are
declined immediately, and the number disappears after the call ends.

**Acceptance Scenarios**:

1. **Given** a number with a saved password, **When** the operator opens it, **Then** the
   password shows as set but its value is never displayed or returned.
2. **Given** an active call on a number, **When** the operator attaches a different inbound
   agent, **Then** the active call keeps its agent and the next call uses the new one.
3. **Given** an active call on a number, **When** the operator deletes it without "Delete when
   idle", **Then** deletion is refused and the message shows how many calls are active.
4. **Given** "Delete when idle" with 2 active calls, **When** confirmed, **Then** the number's
   status becomes "draining", inbound and outbound calls are refused immediately, both active
   calls finish normally, and the number is removed within 1 minute of the last one ending.
5. **Given** a deleted number, **When** past calls are viewed, **Then** they still show the
   number and label they used.

---

### User Story 4 - Answer WhatsApp voice calls with an agent (Priority: P2)

An operator connects a WhatsApp Business number: they enter the business phone number ID, the
phone number, a label, an access token, a verify token of their choosing, and the app secret.
Callwright checks the credentials, enables voice calling for the number, and shows the callback
address to paste into the WhatsApp app settings with the verify token. Once verification
succeeds the channel is active. The operator attaches a default agent; WhatsApp users who call
the business number talk to that agent.

**Why this priority**: WhatsApp voice reaches markets where it is the default calling app, but
operators can launch on phone numbers first.

**Independent Test**: Create a channel with valid test credentials, complete the callback
verification, attach a published agent, place a WhatsApp call to the business number and
confirm the agent answers and the call record has channel "whatsapp".

**Acceptance Scenarios**:

1. **Given** an invalid access token, **When** the channel is created, **Then** it is refused
   with "WhatsApp rejected the access token" and nothing is saved.
2. **Given** a phone number that does not match the business phone number ID, **When** the
   channel is created, **Then** it is refused naming both values.
3. **Given** a saved channel, **When** WhatsApp sends the verification request with the right
   verify token, **Then** Callwright answers the challenge and the channel shows "Verified".
4. **Given** a verification request with a wrong verify token, **When** it arrives, **Then** it
   is refused and no channel changes state.
5. **Given** a notification whose signature does not match the app secret, **When** it arrives,
   **Then** it is rejected and logged.
6. **Given** an active channel with a default agent, **When** a WhatsApp user calls, **Then** the
   agent answers and the call record shows the caller's number and channel "whatsapp".
7. **Given** a channel with no default agent and no route for the caller, **When** a WhatsApp
   user calls, **Then** the call is declined and not charged.
8. **Given** a business phone number ID already registered, **When** another channel is created
   with it, **Then** it is refused with "This WhatsApp number is already connected".

---

### User Story 5 - Route specific WhatsApp callers to specific agents (Priority: P3)

An operator adds caller routes to a WhatsApp channel: a caller's phone number and the agent
that should answer them (for example VIP customers to a premium agent). Callers without a route
reach the default agent.

**Why this priority**: Valuable for segmentation, but most channels run one agent.

**Independent Test**: Add a route for caller A to agent X; call from A and from B; A reaches X,
B reaches the default agent.

**Acceptance Scenarios**:

1. **Given** a route for `+919800000001` to agent X, **When** that caller calls, **Then** agent X
   answers.
2. **Given** a second route for the same caller on the same channel, **When** saved, **Then** it
   is refused as a duplicate.
3. **Given** a route whose agent is later unpublished, **When** that caller calls, **Then** the
   default agent answers and the call record notes the route was skipped.

---

### User Story 6 - Personalise inbound calls from the operator's system (Priority: P3)

An operator sets an inbound webhook on a number or WhatsApp channel. When a call arrives, before
the agent answers, Callwright sends the caller's and the dialled number to that address; the
operator's system can reply with variable values (for example the customer's name and open
order), metadata, a different agent, or an instruction to decline the call.

**Why this priority**: Makes inbound calls feel personal and allows spam blocking, but agents
work without it.

**Independent Test**: Point the inbound webhook at a test endpoint that returns
`{"dynamic_variables": {"customer_name": "Asha"}}`; call the number; the agent greets "Asha".

**Acceptance Scenarios**:

1. **Given** an endpoint that answers within 3 seconds with variables, **When** a call arrives,
   **Then** the agent uses those values.
2. **Given** an endpoint that times out or errors, **When** a call arrives, **Then** the call
   proceeds with the agent's default values and the call record notes the webhook failure.
3. **Given** an endpoint that replies "decline", **When** a call arrives, **Then** the call is
   declined and not charged.
4. **Given** a reply naming an agent from another workspace or an unpublished agent, **When** a
   call arrives, **Then** the reply's agent is ignored and the number's agent answers.

---

### Edge Cases

- A number is imported while the same number is being deleted with "Delete when idle" elsewhere:
  the import is refused until the deletion completes.
- The carrier sends calls for a number before the operator attached an agent: calls are
  declined at the network edge, never billed.
- An attached agent is deleted in the builder: the number keeps working for other direction(s);
  the deleted agent's attachment is cleared and new calls in that direction are declined.
- The operator changes the termination address while an outbound call is ringing: the ringing
  call continues on the old route; new calls use the new one.
- Outbound requests arrive faster than the workspace limit of 10 per second: excess requests are
  refused with "slow down" and a retry hint, before admission.
- The destination number is in a country the carrier cannot reach: the carrier's refusal is
  recorded as status "failed" with the carrier's response code.
- WhatsApp caller numbers arrive without a leading "+": they are normalised to E.164 before
  route lookup and storage.
- The WhatsApp access token expires: the next credential check marks the channel "error" with
  "Access token expired"; editing the token and retrying setup restores it.
- The same E.164 number is connected both as a phone number and as a WhatsApp channel: both work
  and calls are attributed to the right channel.
- An inbound webhook reply is larger than 16 KB or not valid JSON: it is ignored as a failure.

## Requirements *(mandatory)*

### Functional Requirements

**Phone numbers**

- **FR-001**: Users MUST be able to import a phone number with: number in E.164 form (required),
  label (required, 1 to 100 characters), termination address (required, hostname or IPv4/IPv6
  address with optional port), transport (automatic, UDP, TCP or TLS; default automatic),
  optional username and password for the carrier, optional list of allowed source address ranges
  for inbound calls, and optional inbound webhook address.
- **FR-002**: System MUST strip a leading `sip:` or `sips:` scheme from the termination address
  and reject addresses that contain a user part, path or parameters.
- **FR-003**: System MUST keep each number unique across all workspaces while it is active or
  draining, and refuse duplicates without revealing the other workspace.
- **FR-004**: On import, System MUST set up inbound acceptance and an outbound route for the
  number automatically and show status `provisioning`, `active` or `error` (with reason), with a
  "Retry setup" action for `error`.
- **FR-005**: System MUST show the origination address operators configure at their carrier and
  each number's direct address.
- **FR-006**: Users MUST be able to attach and detach one inbound agent and one outbound agent
  per number; attached agents MUST belong to the same workspace and have a published version.
- **FR-007**: When a number has no inbound agent, System MUST decline its inbound calls before
  any agent joins, without creating a call record or charge.
- **FR-008**: Inbound calls to a number with an agent MUST go through the platform's standard
  admission and call lifecycle (003) with channel "phone inbound", "from" set to the caller and
  "to" set to the number, the number's identifier recorded, and the agent's published version.
- **FR-009**: Users MUST be able to edit label, termination address, transport, credentials,
  allowed source ranges, agents and inbound webhook address; the number itself cannot be
  changed. Leaving the password empty on edit MUST keep the stored one; an explicit "remove"
  clears it.
- **FR-010**: System MUST never return or log carrier passwords; responses show only whether a
  password is set.
- **FR-011**: Changes to agents or routing MUST apply only to calls that start after the change.
- **FR-012**: Deleting a number with active calls MUST be refused with the active call count
  unless the operator chooses "Delete when idle", which immediately stops new inbound and
  outbound calls on the number (status `draining`) and removes it within 1 minute after its last
  active call ends. Active calls MUST NOT be interrupted by any edit or deletion.
- **FR-013**: Deleted numbers MUST remain referenced by their past calls (number and label).
- **FR-014**: The number list MUST show number, label, inbound agent, outbound agent, status and
  active call count.

**Outbound calls**

- **FR-015**: Users and API clients MUST be able to request an outbound call with: destination
  (E.164, required), from number (an active number in the workspace, required), agent
  (optional; defaults to the number's outbound agent), dynamic variables (same rules as 003),
  metadata (max 4 KB), and ring timeout (10 to 60 seconds, default 30).
- **FR-016**: Outbound requests MUST carry an idempotency key; a repeat with the same key and
  body within 24 hours MUST return the original call without dialling again; the same key with a
  different body MUST be refused.
- **FR-017**: System MUST refuse outbound requests when: the destination equals the from number,
  the from number is not active, there is no agent, the agent has no published version, the
  workspace exceeds 10 outbound requests per second, or standard admission fails (credit,
  concurrency, unsupported configuration).
- **FR-018**: System MUST record the outcome of every placed outbound call: answered (then the
  normal lifecycle), busy, no answer (including ring timeout) or failed (with the carrier's
  response code); busy, no-answer and failed calls MUST NOT be charged and MUST trigger
  `call_ended`.
- **FR-019**: Voicemail detection, when enabled on the agent, MUST apply to outbound calls (003).
- **FR-020**: The UI MUST offer an outbound call dialog from a number, listing the agent's
  variables pre-filled with defaults, and show "Call started" with the call identifier or the
  refusal reason.

**WhatsApp channels**

- **FR-021**: Users MUST be able to create a WhatsApp channel with: business phone number ID
  (required), phone number in E.164 (required), label (required), access token (required),
  verify token (required, 8 to 128 characters), app secret (required) and platform API version
  (optional; platform default).
- **FR-022**: On creation and on "Retry setup", System MUST check that the access token can read
  the business phone number and that its number matches the one entered, then enable voice
  calling for the number with calls delivered to Callwright; failures MUST be shown with
  WhatsApp's reason and leave nothing half-configured on the Callwright side.
- **FR-023**: System MUST show the callback address and the verify token's role, answer
  WhatsApp's verification challenge only when the verify token matches a channel, and record
  when each channel was verified.
- **FR-024**: System MUST accept WhatsApp notifications only when their signature matches the
  channel's app secret, acknowledge valid ones within 5 seconds, and ignore notifications for
  unknown numbers.
- **FR-025**: Channel status MUST be one of `setup_incomplete` (credentials checked, not yet
  verified), `active`, `error` (with reason), `draining`.
- **FR-026**: Users MUST be able to attach and detach a default inbound agent per channel (same
  rules as FR-006).
- **FR-027**: Inbound WhatsApp calls MUST be routed to the caller's route agent if one exists
  and is published, else the default agent, else declined without charge; routed calls follow
  the standard admission and lifecycle with channel "whatsapp".
- **FR-028**: Users MUST be able to list, add, change and remove caller routes (caller number in
  E.164, agent); caller numbers are unique per channel; at most 1,000 routes per channel.
- **FR-029**: Users MUST be able to edit label, access token (empty keeps), verify token, app
  secret, API version, default agent and inbound webhook address; the business phone number ID
  is fixed. Access token, verify token and app secret are never returned in full.
- **FR-030**: Deleting a channel MUST follow the active-call rules of FR-012 and turn off call
  delivery to Callwright for that number on a best-effort basis.

**Inbound personalisation**

- **FR-031**: When a number or channel has an inbound webhook address, System MUST, before the
  agent answers, send a signed request (same signing scheme as 003 customer webhooks) with the
  call identifier, channel, caller number and dialled number, and wait up to 3 seconds for a
  reply.
- **FR-032**: A reply MAY contain dynamic variables, metadata, an agent (same workspace,
  published) and an action `answer` (default) or `decline`; an invalid, late or failed reply MUST
  be ignored, recorded on the call, and the call MUST proceed with defaults.
- **FR-033**: Inbound webhook addresses MUST pass the same address safety rules as customer
  webhooks (003 FR-040).

**Compliance**

- **FR-034**: Outbound calling MUST [NEEDS CLARIFICATION: Are calling-hour windows (recipient
  local time) and a workspace do-not-call list required in v1, or is compliance the operator's
  responsibility through their own systems?]

### Key Entities

- **Phone Number**: a carrier number the workspace brought; number, label, termination address,
  transport, credential presence, allowed inbound ranges, inbound and outbound agent, inbound
  webhook, status, active call count, and the platform routing references.
- **WhatsApp Channel**: a WhatsApp Business number connected for voice; business phone number
  ID, number, label, credential presence, API version, default agent, inbound webhook, status,
  verification and setup timestamps.
- **Caller Route**: within a WhatsApp channel, a caller number mapped to an agent.
- **Outbound Call Request**: the request that created an outbound call; destination, from
  number, agent, variables, metadata, ring timeout and idempotency key. The resulting call is a
  normal Call (003).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator goes from "Import number" to the first agent-answered inbound call in
  under 10 minutes, excluding time spent in the carrier's own console.
- **SC-002**: 95% of inbound calls hear the agent's first audio within the ring duration plus 2
  seconds.
- **SC-003**: 95% of outbound requests are acknowledged within 1 second and start ringing the
  destination within 2 seconds.
- **SC-004**: Sending the same outbound request with the same idempotency key 100 times places
  exactly one call and one charge.
- **SC-005**: In tests with a simulated carrier, 100% of busy, no-answer and failed outcomes are
  recorded with the right status and no charge.
- **SC-006**: Zero active calls are interrupted by edits, agent changes or deletions in tests.
- **SC-007**: An automated scan of API responses and logs finds no carrier password, access
  token, app secret or verify token in full.
- **SC-008**: 100% of forged or unsigned WhatsApp notifications are rejected; verification
  succeeds on the first attempt when the operator uses the values Callwright shows.

## Assumptions

- Numbers are bring-your-own only; buying numbers through Callwright is out of scope for v1.
- Callwright does not bill carrier or WhatsApp charges; operators pay their carrier and Meta
  directly. Callwright bills calls with its normal per-minute pricing (001).
- WhatsApp support covers user-initiated (inbound) voice calls only; business-initiated
  WhatsApp calls and WhatsApp messaging are out of scope for v1.
- The admission checks, call lifecycle, metering, recording, webhooks and post-call pipeline
  come from 003 unchanged; this feature adds the phone and WhatsApp channels to them.
- Ring duration comes from the agent's configuration (002) and applies to inbound phone and
  WhatsApp calls; outbound calls use the per-request ring timeout instead.
- Outbound campaigns, batch dialling and scheduling are out of scope; clients loop over the
  outbound call API.
- The outbound request rate limit (10 per second per workspace) and the inbound webhook timeout
  (3 seconds) are platform settings that can change per environment.
- Each number belongs to one workspace; moving a number between workspaces means deleting and
  re-importing it.
