# Implementation Plan: Channels (Phone Numbers, Outbound Calls, WhatsApp)

**Branch**: `010-channels` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/010-channels/spec.md`

## Summary

Add the phone and WhatsApp channels on top of the 003 voice runtime. Imported bring-your-own SIP
numbers get a LiveKit SIP inbound trunk, an outbound trunk, and a dispatch rule that exists only
while an inbound agent is attached. Inbound calls (phone and WhatsApp) are routed at claim time by
010's `InboundRouter` implementations and admitted by 003's shared admission. Outbound calls are
admitted by the API and dialled by the worker through the trunk (`worker/telephony.py`), with
SIP outcomes mapped to `busy`, `no_answer` or `failed`. WhatsApp Business voice uses the Cloud
API Calling feature in SIP mode so WhatsApp calls enter LiveKit like phone calls; Callwright
checks credentials, enables calling, verifies the callback and checks notification signatures.
Edits never touch established calls; deletion with active calls drains first.

## Technical Context

**Language/Version**: Python 3.12 (API, worker); TypeScript 5 (web)
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, arq, httpx, `livekit-api`
(SIP trunks, dispatch rules, `CreateSIPParticipant`), `phonenumbers`, respx (tests);
worker: `livekit-agents` 1.x (from 003); web: TanStack Query, Radix dialogs.
**Storage**: PostgreSQL 16 with RLS (`phone_numbers`, `whatsapp_channels`,
`whatsapp_caller_routes`, FKs and two columns on 003's `calls`); Redis for the outbound rate
limit; secrets in 001's `secrets` table.
**Testing**: pytest contract tests per fragment; integration tests with a fake LiveKit client
and respx for the WhatsApp Graph API; worker telephony tests in the 003 offline harness with a
fake SIP participant; optional SIPp end-to-end in quickstart.
**Target Platform**: Linux containers; LiveKit Cloud SIP (or self-hosted `livekit-sip`).
**Project Type**: Web service + realtime worker + SPA.
**Performance Goals**: outbound request acknowledged in under 1 s (p95) and ringing in under 2 s;
inbound first agent audio within ring duration + 2 s (p95); WhatsApp webhook acknowledged in under
5 s; import completes (routing active) in under 30 s.
**Constraints**: Never drop an established call on edit or delete; secrets never returned or
logged; inbound routing must work before a workspace is known while RLS stays enforced.
**Scale/Scope**: up to 1,000 numbers and 50 WhatsApp channels per workspace in v1; 3 API modules,
1 worker module, 1 web route with two tabs.

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design.*

| Gate | Principle | How this plan satisfies it | Status |
|---|---|---|---|
| Vendor behind adapter | I | No STT/LLM/TTS/NC code here; the speech pipeline stays 003's adapters. Telephony runs on the constitution's LiveKit SIP; carriers are bring-your-own and configured as data (address, transport, credentials), never hard-coded. WhatsApp is the channel itself, isolated in `whatsapp/graph_client.py`. | Pass |
| Latency impact stated | II | Not on the per-turn hot path. Inbound adds routing lookup (two indexed reads) and an optional inbound webhook (max 3 s) that overlap the ring duration (research R5, R13), so greeting latency is unchanged when the webhook is faster than the ring time. Outbound dialling happens before `in_progress`. `worker/telephony.py` changes run under 003's benchmark gate (003 T105). | Pass |
| Metering impact stated | III | No new meters. Calls are billed by 003/001 from `connected_at`, so ringing, busy, no-answer, declined and failed calls cost nothing; carrier and Meta charges are the operator's (spec Assumptions). Outbound idempotency prevents double charges (money test T027). | Pass |
| Measurability path | IV | Phone and WhatsApp calls produce the same call records, transcripts, latency and pipeline as web calls, so 006/007/008 work unchanged; routing decisions are recorded in `calls.route_detail`. | Pass |
| Tenancy and privacy | V | RLS on all new tables; the only cross-tenant reads are narrow `SECURITY DEFINER` routing functions that return no secrets (research R4); carrier passwords, WhatsApp tokens, verify tokens, app secrets and Meta SIP credentials stored via `secrets`, masked in responses and redacted in logs (test T038); WhatsApp notifications verified with the app secret; inbound webhook signed and URL-guarded. | Pass |
| Complexity justified | VI | No new deployables or queues; one cron for drain cleanup; per-number SIP objects justified below. | Pass |
| Contract and money tests | VII | Contract tests first for all three fragments (T011, T025, T045); money tests first: outbound idempotency places one call and one charge (T027), declined inbound and no-agent calls create no charge (T012, T062), busy/no-answer/failed outcomes not charged (T028). Worker telephony covered in the offline harness (T015, T029). | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/010-channels/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── phone_numbers.yaml
│   ├── outbound.yaml
│   └── whatsapp.yaml
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
services/api/app/
├── core/
│   ├── livekit.py            # EXTEND (created by 003): SIP inbound/outbound trunks, dispatch rules
│   ├── rate_limit.py         # Redis token bucket (reuse 001's if present)
│   └── logging.py            # EXTEND: redaction filter for secret field names
├── phone_numbers/
│   ├── models.py  schemas.py  service.py  router.py
│   ├── validation.py         # E.164 and termination address parsing (shared with whatsapp, outbound)
│   ├── provisioning.py       # create/update/delete LiveKit SIP objects with compensation
│   ├── routing.py            # InboundRouter for sip_inbound, inbound webhook call
│   └── jobs.py               # drain cleanup cron (numbers and WhatsApp channels)
├── outbound/
│   ├── schemas.py  service.py  router.py   # policies, admission call, OutboundDialProvider
├── whatsapp/
│   ├── models.py  schemas.py  service.py  router.py   # channels, caller routes, public webhook
│   ├── graph_client.py       # WhatsApp Cloud API calls (check number, calling settings, SIP credentials)
│   ├── signatures.py         # X-Hub-Signature-256 verification, verify-token hashing
│   └── routing.py            # InboundRouter for whatsapp
└── migrations/versions/0010_channels.py

services/api/tests/
├── contract/   test_phone_numbers_contract.py  test_outbound_contract.py  test_whatsapp_contract.py
├── unit/       test_validation.py  test_outbound_policies.py  test_whatsapp_signatures.py
│               test_inbound_webhook_reply.py
├── integration/ test_number_provisioning.py  test_inbound_routing.py  test_inbound_declines_no_charge.py
│                test_outbound_idempotency.py  test_outbound_outcomes_no_charge.py  test_number_drain.py
│                test_number_edit.py  test_whatsapp_setup.py  test_whatsapp_webhook.py
│                test_whatsapp_inbound.py  test_caller_routes.py  test_inbound_webhook.py
│                test_rls_channels.py  test_secret_redaction.py
├── fakes/livekit_fake.py
└── e2e/sipp/

services/voice-worker/
├── worker/telephony.py       # NEW: outbound dial, SIP status mapping, inbound ring phase, SIP hangup
└── tests/
    ├── unit/test_telephony.py
    └── harness/scripts/{outbound_answer,outbound_busy,outbound_no_answer,inbound_ring}.yaml

apps/web/src/routes/channels/
├── PhoneNumbersPage.tsx      # /phone-numbers, tabs "SIP numbers" and "WhatsApp channels"
├── components/ImportNumberDialog.tsx  NumberDetailPanel.tsx  OutboundCallDialog.tsx
│              DeleteNumberDialog.tsx  WhatsAppChannelDialog.tsx  WhatsAppChannelPanel.tsx
│              CallerRoutesTable.tsx  SipSettingsCard.tsx
└── hooks/usePhoneNumbers.ts  useWhatsAppChannels.ts
```

**Structure Decision**: Modules match the 010 row of research/architecture.md section 3
(`phone_numbers`, `outbound`, `whatsapp`; web route `/phone-numbers` under `routes/channels/`).
Integration with 003 is only through its documented extension points: `InboundRouter` and
`OutboundDialProvider` registration in `calls/service.py`, `admit()`, `core/livekit.py`,
`core/url_guard.py` and `webhooks_out/signing.py`.

### Call flows

**Inbound phone**: carrier INVITE to LiveKit SIP, inbound trunk matches the number, dispatch rule
creates room `call-in-*` and dispatches `callwright-voice` with
`{"channel":"sip_inbound","route_ref":"num_..."}`; worker claims; 003 calls 010's
`PhoneNumberRouter.resolve()` (routing function, number match check, inbound webhook); 003
admits and returns RuntimeConfig; worker (`telephony.inbound_ring_phase`) posts `ringing`, waits
ring duration, posts `in_progress`, starts the session.

**Outbound**: `POST /v1/outbound-calls`, rate limit, policies, 003 `admit(channel=sip_outbound)`,
create room `call-{call_id}`, dispatch with `{call_id}`, return 202. Worker claims; claim
includes `outbound_dial` from 010's provider; `telephony.dial()` posts `ringing`, creates the
SIP participant, waits for answer, posts `in_progress` or the mapped failure status.

**WhatsApp**: user calls the business number in WhatsApp; Meta sends a SIP INVITE (TLS, SRTP,
Meta credentials) to LiveKit; the channel's inbound trunk and dispatch rule (`route_ref` `wa_...`)
start the same claim path; `WhatsAppRouter.resolve()` applies caller route, then default agent.

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New worker module `worker/telephony.py` (not in architecture section 2 layout) | SIP dialling, status mapping and ring phase are channel logic that must stay out of 003's generic `entry.py` and be testable with a fake SIP participant | Putting SIP code in `entry.py` mixes channel and runtime ownership across features |
| Extra module files `validation.py`, `provisioning.py`, `routing.py`, `graph_client.py`, `signatures.py` | Keep router/service files small; isolate external API clients for faking in tests | One large `service.py` per module is harder to test |
| `SECURITY DEFINER` routing functions | Inbound routing must find the workspace from a number before RLS context exists | Bypassing RLS for the whole claim exposes every table |
| One LiveKit inbound trunk, outbound trunk and dispatch rule per number | Edits, detaches and deletes are isolated; detaching declines calls at the SIP edge with no cost | A shared trunk list races on concurrent edits and couples numbers |
| New ID prefix `wcr_` for caller routes | Routes are addressable resources in the API | Using the caller number as key leaks PII into URLs and logs |
| Columns and FKs added to 003's `calls` table (`ring_timeout_s`, `route_detail`, FKs) | Outbound ring timeout and routing outcome belong on the call | A side table for two fields adds a join to every call read |
