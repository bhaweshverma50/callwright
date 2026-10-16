# Research: Channels

**Feature**: 010-channels | **Date**: 2026-10-16 | **Plan**: [plan.md](./plan.md)

Items marked "verify at implementation" are platform facts to confirm against the pinned
LiveKit and WhatsApp Cloud API versions in the first task that touches them. Each has a stated
fallback that keeps the design intact.

## R1. LiveKit SIP objects per phone number

- **Decision**: One LiveKit inbound trunk and one outbound trunk per imported number, plus one
  dispatch rule that exists only while an inbound agent is attached.
  - Inbound trunk: `numbers=[e164]`, `allowed_addresses` from the number's optional CIDR list,
    no auth (carrier origination rarely supports digest to the callee).
  - Dispatch rule: `dispatch_rule_individual` with `room_prefix="call-in-"`, `trunk_ids=[inbound
    trunk]`, `room_config.agents=[{agent_name: "callwright-voice", metadata:
    '{"channel":"sip_inbound","route_ref":"num_..."}'}]`.
  - Outbound trunk: `address` = termination host[:port], `transport`, `numbers=[e164]`,
    `auth_username` / `auth_password` when set.
- **Rationale**: Per-number objects make every edit, detach and delete a local change with no
  shared list to race on. Removing the dispatch rule on detach makes the SIP layer decline the
  call (no room, no worker job, no call row, no charge), which satisfies FR-007 cheaply.
- **Alternatives**: One shared inbound trunk listing every number (rejected: concurrent edits to
  one list, and one bad number config affects all). Keeping the dispatch rule and hanging up in
  the worker (rejected: spends a worker job and leaves a ringing gap).

## R2. Provisioning and status

- **Decision**: Import inserts the row with status `provisioning` and commits, then calls the
  LiveKit SIP API synchronously (create inbound trunk, outbound trunk, and dispatch rule if an
  agent was given) with a 5-second timeout per call. Success sets `active`; any failure deletes
  what was created (compensation), sets `error` and `status_detail`. `POST
  .../retry-provisioning` repeats the sequence idempotently using the stored ids. Edits that touch
  routing call the update endpoints for trunks (verify at implementation: `UpdateSIPInboundTrunk`
  / `UpdateSIPOutboundTrunk` availability; fallback is create-new-then-delete-old, which is safe
  because active calls do not reference trunks after setup).
- **Rationale**: The SIP API is fast; a synchronous call gives the operator an immediate answer
  in the import dialog, while the stored status covers outages.
- **Alternatives**: An arq job per provisioning (rejected: adds polling to the UI for a sub-second
  operation; kept only for draining cleanup).

## R3. Origination and direct addresses

- **Decision**: `GET /v1/phone-numbers/sip-settings` returns `origination_uri =
  sip:{LIVEKIT_SIP_HOST}` (LiveKit Cloud project SIP host or the self-hosted SIP service), the
  supported transports and `direct_uri_template = sip:{e164}@{LIVEKIT_SIP_HOST}`. Values come
  from configuration, not from the database.

## R4. Inbound routing under row-level security

- **Decision**: 010 registers `InboundRouter` implementations with 003 for `sip_inbound` and
  `whatsapp`. At claim time the workspace is not yet known, so routing reads through two
  `SECURITY DEFINER` SQL functions created in the 010 migration, `route_phone_number(num_id)` and
  `route_whatsapp_channel(wa_id, caller_e164)`, which return only routing columns (workspace,
  status, agent ids, inbound webhook URL). The router checks that the SIP attribute
  `trunk_phone_number` equals the number's E.164 (defence against a misrouted dispatch), then
  sets `app.workspace_id` and continues as a normal tenant-scoped transaction for admission.
- **Rationale**: Keeps RLS strict for every tenant query while allowing the one cross-tenant
  lookup routing needs, with a minimal exposed surface.
- **Alternatives**: A service role that bypasses RLS for the whole claim (rejected: too broad).

## R5. Inbound ring phase

- **Decision**: When the worker claims an inbound phone or WhatsApp call it posts `ringing`,
  runs the inbound webhook (R13) and waits for `max(ring_duration_ms, webhook time)` before
  starting the session and posting `in_progress`. Verify at implementation whether the SIP leg is
  already answered when the participant joins; if it is, the worker plays a standard ringback
  tone during the ring phase so the caller's experience matches. Billing starts at
  `in_progress` (003), so ring time is never billed either way.
- **Rationale**: Ring duration is an agent setting (002, default 5 s) meant to make the pickup
  feel natural; overlapping it with the inbound webhook hides the webhook's latency.

## R6. Outbound dialling

- **Decision**: The API admits the call (003 `admit()` with channel `sip_outbound`), stores the
  ring timeout on the call, creates room `call-{call_id}` and dispatches the worker with
  `{call_id}`. 010 registers an `OutboundDialProvider` so the claim response carries
  `outbound_dial {sip_trunk_id, to_number, from_number, ring_timeout_s}`. The worker
  (`worker/telephony.py`) posts `ringing`, calls `create_sip_participant(room, trunk, call_to,
  participant_identity="callee", wait_until_answered=True, ringing_timeout=...)`, then posts
  `in_progress` on answer and starts the session (agent speaks first per configuration, after
  voicemail detection rules in 003). Failure mapping from the SIP status code in the error
  metadata (verify at implementation: field name):

  | SIP status | Call status | Diagnostic |
  |---|---|---|
  | 486, 600 | `busy` | `sip_486` / `sip_600` |
  | 408, 480, 487, ring timeout | `no_answer` | `sip_<code>` or `ring_timeout` |
  | 403, 404, 484, 488, 503, other 4xx/5xx/6xx | `failed` | `sip_<code>` |
  | trunk unreachable, auth failure (401/407 after retry) | `failed` | `trunk_unreachable` / `trunk_auth_failed` |

- **Rationale**: Dialling from the worker gives one owner for the SIP leg's lifecycle and lets it
  observe the outcome directly; the API stays the only state writer through events.
- **Alternatives**: Dialling from the API right after dispatch (rejected: the API would have to
  watch the SIP participant to learn busy or no answer).

## R7. Idempotency and rate limiting

- **Decision**: `Idempotency-Key` is required on `POST /v1/outbound-calls`; storage and replay
  use `core/idempotency.py` (003) keyed by workspace, endpoint and key, plus the unique
  `calls(workspace_id, idempotency_key)` index as a second guard. A Redis token bucket (10 per
  second, burst 20, per workspace) runs before admission and returns 429 `rate-limited` with
  `Retry-After`.
- **Rationale**: Double dialling a real person is the worst failure for outbound; two layers make
  it impossible even if the replay cache is lost.

## R8. Draining deletion and active-call safety

- **Decision**: Active calls for a number are counted from `calls` in statuses `queued`,
  `ringing` and `in_progress`, by `phone_number_id` (calls in `ended` or later no longer use the
  number). `DELETE` with
  active calls and without `when_idle=true` returns 409 with the count. With `when_idle=true` the
  API deletes the dispatch rule at once, sets status `draining` (outbound validation refuses
  draining numbers), and an arq cron (30 s) finishes the job when the count is zero: delete
  trunks, set `deleted_at`, status `deleted`. Trunk deletion never affects established calls; the
  drain only avoids routing new ones. The same logic applies to WhatsApp channels.
- **Rationale**: FR-012 requires no dropped calls; removing routing first and resources later is
  the simplest order that guarantees it.

## R9. Outbound compliance hook (open clarification)

- **Decision**: Outbound validation runs an ordered list of policy checks
  (`outbound/service.py: OUTBOUND_POLICIES`). v1 ships `same_number`, `number_active`,
  `agent_published` and `rate_limit`. Calling-hour windows and a do-not-call list, if the spec
  clarification requires them, become two more policies with no API change (refusal type
  `outbound-policy`).

## R10. WhatsApp voice calling transport

- **Decision**: Use the WhatsApp Cloud API Calling feature in SIP mode: Meta delivers each
  user-initiated call as a SIP INVITE (TLS, SRTP) to our SIP endpoint, so WhatsApp calls enter
  LiveKit exactly like phone calls. Setup per channel (all with the operator's access token):
  1. `GET /{api_version}/{phone_number_id}?fields=display_phone_number,verified_name` to check
     the token and compare the number (digits only).
  2. `POST /{api_version}/{phone_number_id}/settings` enabling `calling` with SIP enabled and our
     SIP host as the server.
  3. `GET /{api_version}/{phone_number_id}/settings?include_sip_credentials=true` to read the
     per-number SIP credentials Meta will use; store them encrypted.
  4. Create a LiveKit inbound trunk `numbers=[e164]` with those digest credentials, TLS
     transport and required media encryption, and (when a default agent or any route exists) a
     dispatch rule with metadata `{"channel":"whatsapp","route_ref":"wa_..."}`.
  Verify at implementation: exact settings payload, credential field names and whether Meta
  authenticates with digest or by source address; the fallback is `allowed_addresses` set to
  Meta's published SIP ranges.
- **Rationale**: Reuses the whole SIP path (dispatch, worker, recording, metrics) instead of
  building a WebRTC SDP bridge; matches the constitution's "WhatsApp Business Calling via Meta"
  on top of LiveKit SIP.
- **Alternatives**: Graph API signalling with SDP offer/answer through webhooks and a WebRTC
  bridge into LiveKit (rejected: needs a custom media bridge service, Principle VI).

## R11. WhatsApp webhook verification and signatures

- **Decision**: One callback URL for all channels, `/v1/whatsapp/webhook`, because a Meta app has
  one callback URL and may own several numbers. `GET` with `hub.mode=subscribe` looks up the
  channel by `sha256(hub.verify_token)` (indexed column), compares in constant time, returns
  `hub.challenge` as `text/plain` and sets `webhook_verified_at`; no match returns 403. `POST`
  reads `entry[].changes[].value.metadata.phone_number_id`, loads that channel's app secret,
  verifies `X-Hub-Signature-256: sha256=<hex HMAC-SHA256(app_secret, raw body)>`, and returns 200
  within 5 seconds (processing is a quick log plus `last_webhook_at`; call media arrives over
  SIP). Unknown ids return 200 and are dropped to avoid retry storms; bad signatures return 401.
- **Improvement noted**: the reference product collects no app secret and so cannot verify
  notifications.

## R12. Number normalisation

- **Decision**: `phonenumbers` library for E.164 parsing and validation of imported numbers,
  destinations and caller numbers; WhatsApp caller ids (digits without "+") are prefixed with
  "+" and validated. Stored form is always E.164.

## R13. Inbound webhook (`call_inbound`)

- **Decision**: During the ring phase the API (inside claim, via the 010 router) POSTs
  `{event: "call_inbound", event_id, call_id, channel, from_number, to_number,
  phone_number_id | whatsapp_channel_id}` to the configured URL, signed with the workspace secret
  using 003's `webhooks_out/signing.py`, through `core/url_guard.py`, with a 3-second timeout and
  no retries. Accepted reply (max 16 KB JSON): `{action: "answer" | "decline", agent_id?,
  dynamic_variables?, metadata?}`. Invalid or late replies are recorded on the call as
  diagnostic `inbound_webhook_failed:<reason>`. A `decline` produces `admitted: false` and the
  worker hangs up; the call row exists (status `failed`, diagnostic `declined_by_webhook`) but is
  not charged.
- **Rationale**: Gives operators personalisation and spam blocking with one round trip that
  overlaps the ring duration.

## R14. Termination address validation

- **Decision**: Accept `host[:port]` where host is a DNS name (IDNA-encoded, labels 1 to 63
  chars, total at most 253), an IPv4 address or a bracketed IPv6 address; port 1 to 65535. A
  leading `sip:` or `sips:` is stripped (and `sips:` sets transport `tls` if transport was
  `auto`). Anything with `@`, `;`, `/` or `?` is rejected.

## R15. Agent deletion and unpublishing

- **Decision**: Foreign keys from `phone_numbers` and `whatsapp_channels` agent columns and from
  `whatsapp_caller_routes.agent_id` use `ON DELETE SET NULL` / `ON DELETE CASCADE` respectively;
  an after-delete hook in 010 (`phone_numbers/service.py: on_agent_deleted`) removes dispatch
  rules that no longer have an agent. Unpublished agents are checked at routing time (claim), so
  no hook is needed for unpublish.

## R16. Secrets

- **Decision**: Carrier password, WhatsApp access token, verify token, app secret and Meta SIP
  credentials are stored through 001's `secrets` table (KMS-encrypted). Responses carry
  `has_password: true` or `*_last4` only. Logging uses a redaction filter for these field names.

## R17. Testing approach

- **Decision**: Unit and integration tests use a fake LiveKit SIP client (`core/livekit.py` is
  injected) and a fake Graph API (respx). The worker's telephony module is tested in the 003
  offline harness with a fake SIP participant that can answer, reject with a code, or time out.
  An optional end-to-end check in quickstart uses a local `livekit-sip` and SIPp to place real
  SIP calls.
