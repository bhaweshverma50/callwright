---
description: "Task list for 010-channels"
---

# Tasks: Channels (Phone Numbers, Outbound Calls, WhatsApp)

**Input**: Design documents from `specs/010-channels/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md;
003-voice-runtime Phases 1 to 4 merged (admission, claim, events, extension points, harness).

**Tests**: Required (Principle VII). Contract and money tests are written first and must fail
before implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US6 from spec.md

---

## Phase 1: Setup

- [x] T001 [P] Add `phonenumbers` and `respx` to `services/api/pyproject.toml`
- [x] T002 [P] Add settings `LIVEKIT_SIP_HOST`, `WHATSAPP_GRAPH_BASE_URL`, `WHATSAPP_GRAPH_API_VERSION`, `OUTBOUND_RATE_PER_SECOND`, `OUTBOUND_RATE_BURST`, `INBOUND_WEBHOOK_TIMEOUT_S` to `services/api/app/core/config.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 Write migration `services/api/app/migrations/versions/0010_channels.py`: enums `sip_transport`, `channel_status`, `whatsapp_channel_status`; tables `phone_numbers`, `whatsapp_channels`, `whatsapp_caller_routes` with RLS and indexes; FKs and columns `ring_timeout_s`, `route_detail` plus active-call partial indexes on `calls`; `SECURITY DEFINER` routing and lookup functions from data-model.md section 5
- [x] T004 [P] Create `PhoneNumber` ORM model in `services/api/app/phone_numbers/models.py`
- [x] T005 [P] Create `WhatsAppChannel` and `WhatsAppCallerRoute` ORM models in `services/api/app/whatsapp/models.py`
- [x] T006 [P] Unit tests for E.164 parsing, termination address rules (scheme stripping, IPv6, rejected user part, path, params) and CIDR lists in `services/api/tests/unit/test_validation.py`
- [x] T007 Implement validation helpers in `services/api/app/phone_numbers/validation.py` (depends on T006)
- [x] T008 [P] Extend `services/api/app/core/livekit.py` with SIP inbound and outbound trunk create, update, delete and dispatch rule create and delete
- [x] T009 [P] Implement the Redis token bucket in `services/api/app/core/rate_limit.py` (reuse 001's if present)
- [x] T010 [P] Add a fake LiveKit SIP client fixture in `services/api/tests/fakes/livekit_fake.py` and a fake SIP participant (answer, reject with code, time out, hang up) to `services/voice-worker/tests/harness/fakes.py`

**Checkpoint**: schema, validation and fakes ready.

---

## Phase 3: User Story 1 - Import a number and let an agent answer it (Priority: P1) MVP

**Goal**: Import with automatic routing setup, attach an inbound agent, answer inbound calls.

**Independent Test**: Import, attach a published agent, place a SIP call to the number; the agent
greets; the call row has channel `sip_inbound`, correct from/to and `phone_number_id`.

### Tests for User Story 1 (write first, must fail)

- [x] T011 [P] [US1] Contract test for `/v1/phone-numbers`, `/v1/phone-numbers/sip-settings`, `/v1/phone-numbers/{number_id}` (GET, PATCH agent fields) and `/retry-provisioning` against `contracts/phone_numbers.yaml` in `services/api/tests/contract/test_phone_numbers_contract.py`
- [x] T012 [P] [US1] Money test: a number without an inbound agent has no dispatch rule (no call row, no charge); an unpublished agent at routing time yields `admitted: false` and a `failed` call with no charge in `services/api/tests/integration/test_inbound_declines_no_charge.py`
- [x] T013 [P] [US1] Integration test for import: active on success, `error` with compensation on platform failure, retry to active, global duplicate refused without workspace detail, `sip:` prefix stripped in `services/api/tests/integration/test_number_provisioning.py`
- [x] T014 [P] [US1] Integration test for inbound claim routing: admitted with from/to and `phone_number_id`, trunk-number mismatch refused, non-active number refused in `services/api/tests/integration/test_inbound_routing.py`
- [x] T015 [P] [US1] Worker tests for the inbound ring phase (`ringing` then `in_progress` after ring duration, caller hangup during ring gives `failed` without connect, hangup after connect gives `user_hangup`) in `services/voice-worker/tests/unit/test_telephony.py` and `services/voice-worker/tests/harness/scripts/inbound_ring.yaml` (done as unit tests with the fake SIP room and dialer in `tests/harness/fakes.py`; no harness YAML)
- [x] T080 [P] [US1] Contract and integration test: `POST /v1/phone-numbers` with an extra `user_id` or `workspace_id` field returns 422 and the number is created in the token's workspace only in `services/api/tests/integration/test_number_body_scoping.py`

### Implementation for User Story 1

- [x] T016 [US1] Implement SIP object provisioning with compensation and idempotent retry (research R1, R2) in `services/api/app/phone_numbers/provisioning.py`
- [x] T017 [US1] Implement import, list (with active call counts), get, retry and agent attach/detach (published check, dispatch rule create/delete) in `services/api/app/phone_numbers/service.py` and `services/api/app/phone_numbers/schemas.py`
- [x] T018 [US1] Implement routes `GET/POST /v1/phone-numbers`, `GET /v1/phone-numbers/sip-settings`, `GET/PATCH /v1/phone-numbers/{number_id}` (agent fields), `POST .../retry-provisioning` in `services/api/app/phone_numbers/router.py`
- [x] T019 [US1] Implement `PhoneNumberRouter` (routing function, trunk-number check, published agent, `route_detail`) and register it with 003's `InboundRouter` registry in `services/api/app/phone_numbers/routing.py`
- [x] T020 [US1] Implement the inbound ring phase and SIP participant hangup detection in `services/voice-worker/worker/telephony.py` and register `sip_inbound` and `whatsapp` channel handlers in `services/voice-worker/worker/entry.py`
- [x] T021 [P] [US1] Implement `usePhoneNumbers` queries and mutations in `apps/web/src/routes/channels/hooks/usePhoneNumbers.ts`
- [x] T022 [P] [US1] Implement `ImportNumberDialog` and `SipSettingsCard` (copyable origination address) in `apps/web/src/routes/channels/components/ImportNumberDialog.tsx` and `apps/web/src/routes/channels/components/SipSettingsCard.tsx`
- [x] T023 [US1] Implement `PhoneNumbersPage` (tabs, list, empty state) and `NumberDetailPanel` (status, retry, inbound agent select) and register `/phone-numbers` in `apps/web/src/app/router.tsx`; files `apps/web/src/routes/channels/PhoneNumbersPage.tsx`, `apps/web/src/routes/channels/components/NumberDetailPanel.tsx`
- [x] T024 [US1] Add `phone_numbers.yaml` to the `contracts/openapi.yaml` assembly and regenerate `apps/web/src/api/`
- [x] T081 [US1] Client-side validation in `ImportNumberDialog` mirroring the server rules (required fields on empty submit, E.164 with example, termination host or IP with optional port, user part or path rejected), server `errors[]` mapped to fields, plus web tests in `apps/web/src/routes/channels/components/ImportNumberDialog.tsx` and `apps/web/src/routes/channels/components/ImportNumberDialog.test.tsx`
- [x] T082 [US1] Use the same name ("Channels") for the sidebar entry and the page title of `/phone-numbers` in `apps/web/src/routes/channels/PhoneNumbersPage.tsx` and the shell navigation config `apps/web/src/app/navigation.ts` (shared shell file owned by 001)

**Checkpoint**: Imported numbers answer inbound calls with an agent.

---

## Phase 4: User Story 2 - Place outbound calls from a number (Priority: P1)

**Goal**: Outbound API and dialog with idempotency, policies (including the do-not-call list and
calling hours, spec FR-034 to FR-038), dialling and outcome mapping.

**Independent Test**: Outbound call to a test destination is answered by the agent; replay with
the same key places no second call; a do-not-call destination is blocked with `dnc_listed` and
a request outside the recipient's calling hours with `outside_calling_hours`, neither creating
a call or charge.

### Tests for User Story 2 (write first, must fail)

- [x] T025 [P] [US2] Contract test for `POST /v1/outbound-calls` against `contracts/outbound.yaml` in `services/api/tests/contract/test_outbound_contract.py`
- [x] T026 [P] [US2] Unit tests for outbound policies (same number, number not active or draining, no outbound agent, unpublished agent, rate limit) in `services/api/tests/unit/test_outbound_policies.py`
- [x] T027 [P] [US2] Money test: 100 replays with one key place one call and one `call_charge`; same key with a different body returns 422; missing key returns 400 in `services/api/tests/integration/test_outbound_idempotency.py`
- [x] T028 [P] [US2] Money test: busy, no-answer, ring-timeout and failed outcomes have zero billable seconds, no charge, and enqueue `call_ended` in `services/api/tests/integration/test_outbound_outcomes_no_charge.py`
- [x] T029 [P] [US2] Worker tests for dialling and SIP status mapping (486, 600, 408, 480, 487, 403, 404, 503, auth failure, ring timeout) in `services/voice-worker/tests/unit/test_telephony.py` and harness scripts `outbound_answer.yaml`, `outbound_busy.yaml`, `outbound_no_answer.yaml` in `services/voice-worker/tests/harness/scripts/` (done as unit tests with `FakeSipDialer`; no harness YAML)
- [x] T070 [P] [US2] Contract test for `/v1/dnc-entries`, `/v1/dnc-entries/{dnc_id}`, `/v1/dnc-entries/import`, `/v1/outbound-calling-hours`, `/v1/outbound-policy-decisions` and the `PolicyBlockedProblem` 422 body of `POST /v1/outbound-calls` against `contracts/outbound.yaml` in `services/api/tests/contract/test_outbound_compliance_contract.py`
- [x] T071 [P] [US2] Unit tests for calling-hour evaluation (default 09:00 to 21:00, per-weekday windows, `null` day, `24:00` end, start not before end rejected, DST day, recipient local weekday, override precedence, invalid override, multi-zone all-zones rule, unknown zone blocks, `next_allowed_at`) in `services/api/tests/unit/test_calling_hours.py`
- [x] T072 [P] [US2] Unit tests for do-not-call normalisation and CSV import (E.164 and national formats with `default_region`, duplicates in file and already listed, invalid rows with row numbers, missing `number` header, row and size limits) in `services/api/tests/unit/test_dnc_import.py`
- [x] T073 [P] [US2] Money test: `dnc_listed` and `outside_calling_hours` requests return 422 with the reason, create no `calls` row, no LiveKit dispatch and no `call_charge`, write one `outbound_policy_decisions` row, and are not stored against the Idempotency-Key (a retry after removing the entry dials once); DNC wins when both apply in `services/api/tests/integration/test_outbound_compliance_no_charge.py`

### Implementation for User Story 2

- [x] T030 [US2] Implement outbound service: rate limit, ordered policies (`OUTBOUND_POLICIES`), 003 `admit(channel="sip_outbound")` with idempotency key and `ring_timeout_s`, room creation and dispatch in `services/api/app/outbound/service.py` and `services/api/app/outbound/schemas.py`
- [x] T031 [US2] Implement `POST /v1/outbound-calls` with required Idempotency-Key and problem mapping in `services/api/app/outbound/router.py`
- [x] T032 [US2] Implement and register the `OutboundDialProvider` (trunk id, numbers, ring timeout) with 003 in `services/api/app/outbound/service.py`
- [x] T033 [US2] Implement `dial()` (post `ringing`, create SIP participant, wait for answer, post `in_progress` or mapped status with `sip_<code>` diagnostic) in `services/voice-worker/worker/telephony.py`
- [x] T034 [P] [US2] Implement `OutboundCallDialog` (destination, variables pre-filled from agent defaults, result message) in `apps/web/src/routes/channels/components/OutboundCallDialog.tsx`
- [x] T035 [US2] Add outbound agent select and "Make outbound call" to `apps/web/src/routes/channels/components/NumberDetailPanel.tsx`; add `outbound.yaml` to the contract assembly and regenerate `apps/web/src/api/`
- [x] T074 [US2] Extend migration `services/api/app/migrations/versions/0010_channels.py` with enums `dnc_source`, `outbound_block_reason`, `timezone_source` and tables `dnc_entries`, `outbound_calling_hours`, `outbound_policy_decisions` (RLS, constraints, indexes from data-model.md sections 7 to 9), and create the ORM models in `services/api/app/outbound/models.py`
- [x] T075 [US2] Implement do-not-call list, search, add (409 on duplicate), remove and CSV import (`phonenumbers` normalisation, `ON CONFLICT DO NOTHING`, invalid-row report, 1,000,000-entry cap) in `services/api/app/outbound/dnc.py` and routes `GET/POST /v1/dnc-entries`, `DELETE /v1/dnc-entries/{dnc_id}`, `POST /v1/dnc-entries/import` in `services/api/app/outbound/router.py`
- [x] T076 [US2] Implement calling-hour settings (lazy default row, `GET/PUT /v1/outbound-calling-hours`) and the evaluator (recipient zone from override or `phonenumbers.timezone`, `zoneinfo` conversion, multi-zone rule, `next_allowed_at`) in `services/api/app/outbound/calling_hours.py` and `services/api/app/outbound/router.py`
- [x] T068 [US2] Register the `dnc_listed` and `outside_calling_hours` policies in `OUTBOUND_POLICIES` after `agent_published`, return `PolicyBlockedProblem` (422, type `outbound-policy`), write the `outbound_policy_decisions` row in its own transaction, skip Idempotency-Key storage for blocks, accept `recipient_timezone` and return `recipient_timezones` and `timezone_source` on success in `services/api/app/outbound/service.py`, `services/api/app/outbound/schemas.py` and `services/api/app/outbound/router.py` (moved here from Polish; uses T075, T076)
- [x] T077 [US2] Implement `GET /v1/outbound-policy-decisions` (filters `reason`, `to_number`, `since`; newest first) in `services/api/app/outbound/service.py` and `services/api/app/outbound/router.py`
- [x] T078 [P] [US2] Implement `useOutboundCompliance` and a "Compliance" tab on `/phone-numbers` with the do-not-call list (search, add, remove), `DncImportDialog` (CSV upload, default region, result counts and invalid rows), `CallingHoursEditor` (per-weekday start, end or no calls) and recent blocked attempts, in `apps/web/src/routes/channels/hooks/useOutboundCompliance.ts`, `apps/web/src/routes/channels/components/ComplianceTab.tsx`, `apps/web/src/routes/channels/components/DncImportDialog.tsx`, `apps/web/src/routes/channels/components/CallingHoursEditor.tsx` and `apps/web/src/routes/channels/PhoneNumbersPage.tsx`
- [x] T079 [US2] Add an optional recipient timezone field and specific block messages (`dnc_listed`, `outside_calling_hours` with local time and next allowed time) to `apps/web/src/routes/channels/components/OutboundCallDialog.tsx` (after T034)

**Checkpoint**: Outbound calling works from API and UI with no double dialling, and do-not-call and calling-hour blocks are enforced before dialling.

---

## Phase 5: User Story 3 - Edit and remove numbers without dropping calls (Priority: P2)

**Goal**: Full edit with masked credentials; draining deletion; agent-deletion cleanup.

**Independent Test**: With an active call, change the agent and "Delete when idle"; the call
continues, new calls are refused, the number is removed after the call ends.

### Tests for User Story 3 (write first, must fail)

- [x] T036 [P] [US3] Integration test for deletion: 409 with active count; `when_idle` sets `draining`, removes the dispatch rule, refuses outbound, cleanup deletes after zero active calls within one cron cycle, past calls keep number and label in `services/api/tests/integration/test_number_drain.py`
- [x] T037 [P] [US3] Integration test for edits: password kept when omitted, removed with `remove_auth_password`, termination and transport changes update the outbound trunk, agent changes leave active calls on their agent in `services/api/tests/integration/test_number_edit.py`
- [x] T038 [P] [US3] Secret exposure test: no response body or captured log line contains a stored carrier password, access token, verify token, app secret or Meta SIP credential in `services/api/tests/integration/test_secret_redaction.py`

### Implementation for User Story 3

- [x] T039 [US3] Extend PATCH to label, termination address, transport, credentials, allowed CIDRs and inbound webhook URL, with trunk update or recreate-then-delete fallback in `services/api/app/phone_numbers/service.py` and `services/api/app/phone_numbers/provisioning.py`
- [x] T040 [US3] Implement `DELETE /v1/phone-numbers/{number_id}` with `when_idle` in `services/api/app/phone_numbers/service.py` and `services/api/app/phone_numbers/router.py`
- [x] T041 [US3] Implement the drain cleanup cron (30 s, numbers and WhatsApp channels) in `services/api/app/phone_numbers/jobs.py` and register it in `services/api/app/jobs.py`
- [x] T042 [US3] Add a log redaction filter for secret field names in `services/api/app/core/logging.py`
- [x] T043 [US3] Implement `on_agent_deleted` (clear attachments, delete orphaned dispatch rules) subscribed to 002's agent deletion in `services/api/app/phone_numbers/service.py` (done as 002's usage checker: deleting an attached agent is refused with `agent_in_use` listing the numbers and channels)
- [x] T044 [P] [US3] Implement `DeleteNumberDialog` (active count, "Delete when idle") and the editable detail form with change tracking in `apps/web/src/routes/channels/components/DeleteNumberDialog.tsx` and `apps/web/src/routes/channels/components/NumberDetailPanel.tsx`

**Checkpoint**: Numbers are safe to change at any time.

---

## Phase 6: User Story 4 - Answer WhatsApp voice calls with an agent (Priority: P2)

**Goal**: Create a channel with credential check and calling setup, verify the callback,
validate signatures, route calls to the default agent.

**Independent Test**: Create a channel with test credentials, verify the callback, attach an agent,
place a WhatsApp call; the call row has channel `whatsapp`.

### Tests for User Story 4 (write first, must fail)

- [x] T045 [P] [US4] Contract test for `/v1/whatsapp/settings`, `/v1/whatsapp/channels*` and `/v1/whatsapp/webhook` against `contracts/whatsapp.yaml` in `services/api/tests/contract/test_whatsapp_contract.py`
- [x] T046 [P] [US4] Unit tests for `X-Hub-Signature-256` verification (valid, tampered body, wrong secret, malformed header) and verify-token hashing in `services/api/tests/unit/test_whatsapp_signatures.py`
- [x] T047 [P] [US4] Integration test for setup with respx: token rejected saves nothing; number mismatch names both values; success gives `setup_incomplete`; trunk failure gives `error` with compensation; retry recovers; duplicate business id refused in `services/api/tests/integration/test_whatsapp_setup.py`
- [x] T048 [P] [US4] Integration test for the public webhook: challenge echoed and `webhook_verified_at` set (`active`), wrong token 403, bad signature 401, unknown id 200 ignored, response under 5 s in `services/api/tests/integration/test_whatsapp_webhook.py`
- [x] T049 [P] [US4] Integration test for WhatsApp claim routing: default agent admitted with channel `whatsapp` and normalised caller number; no agent declined with no charge in `services/api/tests/integration/test_whatsapp_inbound.py`
- [x] T083 [P] [US4] Integration test with respx: WhatsApp connection error or timeout during create returns 502 `whatsapp-unreachable` and saves nothing; non-numeric `meta_phone_number_id` returns 422 with a field error in `services/api/tests/integration/test_whatsapp_setup.py`

### Implementation for User Story 4

- [x] T050 [P] [US4] Implement the WhatsApp Cloud API client (number check, calling settings with SIP, SIP credentials read, calling disable) in `services/api/app/whatsapp/graph_client.py`
- [x] T051 [P] [US4] Implement signature verification and verify-token hashing in `services/api/app/whatsapp/signatures.py`
- [x] T052 [US4] Implement channel create, update (token keep-if-empty), retry setup and delete (drain rules, best-effort calling disable) with secrets via 001 in `services/api/app/whatsapp/service.py` and `services/api/app/whatsapp/schemas.py`
- [x] T053 [US4] Implement authenticated channel routes, `GET /v1/whatsapp/settings`, and public `GET/POST /v1/whatsapp/webhook` in `services/api/app/whatsapp/router.py`
- [x] T054 [US4] Implement `WhatsAppRouter` (caller normalisation, default agent, decline without agent) and register it with 003 in `services/api/app/whatsapp/routing.py`
- [x] T055 [P] [US4] Implement `useWhatsAppChannels` in `apps/web/src/routes/channels/hooks/useWhatsAppChannels.ts`
- [x] T084 [US4] Map connection failures in `services/api/app/whatsapp/graph_client.py` to `whatsapp-unreachable` (502) in `services/api/app/whatsapp/service.py`
- [x] T056 [US4] Implement `WhatsAppChannelDialog` and `WhatsAppChannelPanel` (setup checklist: credentials, calling, verified; copyable callback URL; default agent select) in `apps/web/src/routes/channels/components/WhatsAppChannelDialog.tsx` and `apps/web/src/routes/channels/components/WhatsAppChannelPanel.tsx`; add `whatsapp.yaml` to the contract assembly and regenerate `apps/web/src/api/`
- [x] T085 [US4] `WhatsAppChannelDialog` form rules: digits-only business phone number ID, E.164 number, verify token length, API version prefilled from `GET /v1/whatsapp/settings`, read-only callback address with copy, setup guide link, cause-specific failure messages keeping non-secret values, plus web tests in `apps/web/src/routes/channels/components/WhatsAppChannelDialog.tsx` and `apps/web/src/routes/channels/components/WhatsAppChannelDialog.test.tsx`

**Checkpoint**: WhatsApp voice calls reach agents.

---

## Phase 7: User Story 5 - Route specific WhatsApp callers to specific agents (Priority: P3)

**Goal**: Caller route CRUD and routing precedence.

**Independent Test**: Route caller A to agent X; A reaches X, B reaches the default agent.

- [x] T057 [P] [US5] Integration test for routes: create, duplicate refused, 1,000 limit, update agent, delete, precedence over default, unpublished route agent skipped with `route_detail` in `services/api/tests/integration/test_caller_routes.py`
- [x] T058 [US5] Implement caller route list, create, update and delete in `services/api/app/whatsapp/service.py` and `services/api/app/whatsapp/router.py`
- [x] T059 [US5] Apply route precedence in `services/api/app/whatsapp/routing.py` and keep the dispatch rule present when routes exist without a default agent in `services/api/app/whatsapp/service.py`
- [x] T060 [P] [US5] Implement `CallerRoutesTable` (search, add, change agent, remove, skipped badge) in `apps/web/src/routes/channels/components/CallerRoutesTable.tsx`

---

## Phase 8: User Story 6 - Personalise inbound calls from the operator's system (Priority: P3)

**Goal**: Signed `call_inbound` request during the ring phase; apply or ignore the reply.

**Independent Test**: Endpoint returns `customer_name: Asha`; the agent greets Asha.

- [x] T061 [P] [US6] Unit tests for reply parsing (size limit, invalid JSON, foreign or unpublished agent ignored, `decline`) in `services/api/tests/unit/test_inbound_webhook_reply.py`
- [x] T062 [P] [US6] Money and integration test: variables applied; timeout uses defaults and records `inbound_webhook_failed:timeout`; `decline` gives `failed` with `declined_by_webhook` and no charge; private URL blocked in `services/api/tests/integration/test_inbound_webhook.py`; add a `--reply <json>` option to 003's `services/api/tests/integration/tools/flaky_receiver.py`
- [x] T063 [US6] Implement the inbound webhook call (003 signing, URL guard, 3 s timeout, no retry) shared by both routers in `services/api/app/phone_numbers/routing.py` and use it from `services/api/app/whatsapp/routing.py`
- [x] T064 [US6] Add the inbound webhook URL field with "Send test event" (003 `POST /v1/webhooks/test`) to `apps/web/src/routes/channels/components/NumberDetailPanel.tsx` and `apps/web/src/routes/channels/components/WhatsAppChannelPanel.tsx`

---

## Phase 9: Polish & Cross-Cutting Concerns

- [x] T065 [P] RLS isolation tests for all 010 tables (including `dnc_entries`, `outbound_calling_hours`, `outbound_policy_decisions`) and a check that routing and lookup functions return no secret columns in `services/api/tests/integration/test_rls_channels.py`
- [x] T066 [P] Add OpenTelemetry spans for provisioning, routing, inbound webhook and dialling (`call_id`, `phone_number_id`, `whatsapp_channel_id`) in `services/api/app/phone_numbers/provisioning.py`, `services/api/app/phone_numbers/routing.py` and `services/voice-worker/worker/telephony.py`
- [ ] T067 [P] Add an optional SIPp end-to-end scenario (inbound answer, outbound busy) in `services/api/tests/e2e/sipp/` used by quickstart section 6
- [ ] T069 Run every section of `specs/010-channels/quickstart.md` and fix drift

---

## Dependencies & Execution Order

### Phase Dependencies

- 003 Phases 1 to 4 (admission, claim, events, reaper, harness, extension points) must be
  merged first; 003 US4 (pipeline) is needed for the money tests T027, T028 and T062 that assert
  on charges.
- Setup, then Foundational (blocks all stories).
- US1 before US2 (outbound needs imported active numbers and `NumberDetailPanel`).
- US3 after US1 (extends the same service and panel); can run alongside US2 on different files.
- US4 after Foundational; independent of US1 to US3 except the shared drain cron (T041) for
  WhatsApp deletion.
- US5 after US4. US6 after US1 (and US4 for the WhatsApp half).
- Changes to `services/voice-worker/worker/telephony.py` run under 003's latency benchmark gate.

### Within Each User Story

- Tests first and failing; models, then services, then routers, then web.

## Parallel Example: User Story 2

```bash
Task: "T025 Contract test outbound in services/api/tests/contract/test_outbound_contract.py"
Task: "T026 Outbound policies unit tests in services/api/tests/unit/test_outbound_policies.py"
Task: "T027 Idempotency money test in services/api/tests/integration/test_outbound_idempotency.py"
Task: "T028 Outcome no-charge money test in services/api/tests/integration/test_outbound_outcomes_no_charge.py"
Task: "T029 Telephony mapping tests in services/voice-worker/tests/unit/test_telephony.py"
Task: "T070 Compliance contract test in services/api/tests/contract/test_outbound_compliance_contract.py"
Task: "T071 Calling-hour unit tests in services/api/tests/unit/test_calling_hours.py"
Task: "T072 DNC import unit tests in services/api/tests/unit/test_dnc_import.py"
Task: "T073 Compliance no-charge money test in services/api/tests/integration/test_outbound_compliance_no_charge.py"
```

## Implementation Strategy

### MVP First

1. Setup and Foundational.
2. US1: import and inbound answering. Validate with quickstart sections 2 and 3.
3. US2: outbound. Validate with quickstart section 4.

### Incremental Delivery

US3 (safe edits) before opening to production traffic, then US4 (WhatsApp), US5 and US6.
