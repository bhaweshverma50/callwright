# Feature specification: scheduled callbacks (011)

Created: 2026-11-03. Status: implemented on branch `w7-callbacks`.

## Why
On a lab SIP call the caller said "I have a meeting, can you call me back later?" and the agent
could only hang up. Outbound calls (010) are placed immediately and the agent had no way to book
one for later.

## User stories
1. **Caller asks for a callback (P1).** The agent asks when (if not said), books it, says the
   confirmed time back in the caller's local time and ends the call politely. At that time the
   same agent calls back from the same number, knowing why (the note).
2. **Operator sees and manages callbacks (P1).** The source call's drawer shows the booked
   callback with its status and a Cancel action; a Callbacks list shows every callback with a
   status filter and links to the source and resulting calls.
3. **Client schedules through the API (P2).** `POST /v1/callbacks` books an outbound call for
   later with the same checks as `POST /v1/outbound-calls`.

## Requirements
- FR-001: A callback stores workspace, number to call from, destination, agent, time (UTC, with
  the recipient's zone for display), note, source call, carried dynamic variables (non built-in,
  plus `callback_note`), who booked it (`agent` or `api`), status, failure reason and the
  resulting call.
- FR-002: Status flow `scheduled` to `placing` to `placed` or `failed`; `scheduled` to
  `cancelled`. Only scheduled callbacks can be cancelled.
- FR-003: Booking runs 010's outbound policies with the calling hours checked at the booked
  time. A do-not-call destination or a time outside calling hours is refused; outside hours
  the refusal carries the next allowed time so the agent can offer it. Times must be 1 minute
  to 30 days ahead.
- FR-004: A cron places due callbacks every minute through 010's outbound path (policies at dial
  time, logged as policy decisions when they block; 003 admission for credit, concurrency and
  configuration), with idempotency key `callback:<id>` so a callback dials at most once.
- FR-005: When every call slot is busy the callback waits for the next run. A callback not placed
  within 30 minutes of its time fails as `missed`. Every other refusal fails it with its code.
- FR-006: The agent's tool is refused on calls that are not phone calls (browser test calls,
  WhatsApp) with a sentence the agent can relay, and nothing is stored. Simulations (008) get a
  mocked booking and never store one.
- FR-007: A second booking on the same call moves the scheduled callback instead of adding one.
- FR-008: Callbacks are tenant data under row-level security.

## Out of scope
Recurring callbacks, retries after a missed or unanswered callback, WhatsApp callbacks (010 has no
WhatsApp outbound). Flow agents were out of scope at first; since 2026-11-03 every conversational
flow node has `schedule_callback` too (docs/OPERATIONS.md section 14).
