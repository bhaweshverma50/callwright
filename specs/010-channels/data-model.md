# Data Model: Channels

**Feature**: 010-channels | **Date**: 2026-10-16 | **Plan**: [plan.md](./plan.md)

All tables carry `workspace_id` with row-level security as in research/architecture.md
section 4. Secrets are references into 001's `secrets` table (KMS-encrypted). Migration:
`services/api/app/migrations/versions/0010_channels.py` (forward-only).

## 1. `phone_numbers` (module `phone_numbers`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | text PK | no | `num_` ULID |
| workspace_id | text FK workspaces | no | RLS |
| e164 | text | no | `^\+[1-9]\d{1,14}$`, validated with `phonenumbers` |
| label | text | no | 1 to 100 chars |
| termination_host | text | no | DNS name, IPv4 or bracketed IPv6 (research R14) |
| termination_port | integer | yes | 1 to 65535 |
| transport | enum `sip_transport` | no | `auto` (default), `udp`, `tcp`, `tls` |
| auth_username | text | yes | carrier username (not secret) |
| auth_password_secret_id | text FK secrets | yes | never returned |
| inbound_allowed_cidrs | cidr[] | no | default `{}` (any source) ; max 20 entries |
| inbound_agent_id | text FK agents ON DELETE SET NULL | yes | |
| outbound_agent_id | text FK agents ON DELETE SET NULL | yes | |
| inbound_webhook_url | text | yes | HTTPS, passes URL guard |
| lk_inbound_trunk_id | text | yes | LiveKit `ST_...` |
| lk_outbound_trunk_id | text | yes | LiveKit `ST_...` |
| lk_dispatch_rule_id | text | yes | LiveKit `SDR_...`; null whenever `inbound_agent_id` is null |
| status | enum `channel_status` | no | `provisioning`, `active`, `error`, `draining`, `deleted` |
| status_detail | text | yes | human-readable reason for `error` |
| created_at, updated_at | timestamptz | no | |
| deleted_at | timestamptz | yes | soft delete; row kept for call history |

**Constraints and indexes**: `UNIQUE (e164) WHERE deleted_at IS NULL` (global, FR-003);
`(workspace_id, created_at DESC)`.

### Phone number states

| From | To | Trigger |
|---|---|---|
| (new) | `provisioning` | import accepted |
| `provisioning` | `active` | all LiveKit objects created |
| `provisioning`, `active` | `error` | LiveKit call failed (compensated) |
| `error` | `provisioning` | retry setup |
| `active`, `error` | `draining` | delete with `when_idle=true` and active calls > 0 (dispatch rule removed at once) |
| `active`, `error` | `deleted` | delete with no active calls (LiveKit objects removed) |
| `draining` | `deleted` | cleanup cron sees zero active calls |

Rules: outbound requests and new attachments require `active`. Inbound routing ignores any
status other than `active` (the dispatch rule is also absent outside `active`).

## 2. `whatsapp_channels` (module `whatsapp`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | text PK | no | `wa_` ULID |
| workspace_id | text FK workspaces | no | RLS |
| meta_phone_number_id | text | no | digits, 5 to 32 chars |
| e164 | text | no | business number |
| label | text | no | 1 to 100 chars |
| access_token_secret_id | text FK secrets | no | |
| verify_token_secret_id | text FK secrets | no | |
| verify_token_hash | text | no | SHA-256 hex of the verify token, for webhook lookup |
| app_secret_secret_id | text FK secrets | no | |
| graph_api_version | text | no | `^v?\d+\.\d+$`, default from `WHATSAPP_GRAPH_API_VERSION` |
| sip_credentials_secret_id | text FK secrets | yes | Meta-issued SIP credentials (research R10) |
| inbound_agent_id | text FK agents ON DELETE SET NULL | yes | default agent |
| inbound_webhook_url | text | yes | |
| lk_inbound_trunk_id | text | yes | |
| lk_dispatch_rule_id | text | yes | present when a default agent or at least one route exists |
| status | enum `whatsapp_channel_status` | no | `setup_incomplete`, `active`, `error`, `draining`, `deleted` |
| status_detail | text | yes | |
| credentials_verified_at | timestamptz | yes | |
| calling_enabled_at | timestamptz | yes | |
| webhook_verified_at | timestamptz | yes | |
| last_webhook_at | timestamptz | yes | |
| created_at, updated_at, deleted_at | timestamptz | | |

**Constraints and indexes**: `UNIQUE (meta_phone_number_id) WHERE deleted_at IS NULL`;
`UNIQUE (verify_token_hash) WHERE deleted_at IS NULL` (a verify token identifies one channel);
`(workspace_id, created_at DESC)`.

### WhatsApp channel states

| From | To | Trigger |
|---|---|---|
| (new) | `setup_incomplete` | credentials checked, calling enabled, LiveKit trunk created |
| `setup_incomplete` | `active` | verification challenge answered (`webhook_verified_at` set) |
| any non-deleted | `error` | credential check, calling settings or trunk creation failed; token rejected later |
| `error` | `setup_incomplete` or `active` | retry setup succeeds (`active` if already verified) |
| `active`, `setup_incomplete`, `error` | `draining` / `deleted` | delete, same rules as phone numbers |

Creation that fails the credential check saves nothing (FR-022); failures after a successful
credential check save the channel in `error` with compensation of partial LiveKit objects.

## 3. `whatsapp_caller_routes` (module `whatsapp`)

| Column | Type | Notes |
|---|---|---|
| id | text PK | `wcr_` ULID (new prefix, see plan Complexity Tracking) |
| workspace_id | text | RLS |
| channel_id | text FK whatsapp_channels ON DELETE CASCADE | |
| caller_e164 | text | normalised E.164 |
| agent_id | text FK agents ON DELETE CASCADE | |
| created_at, updated_at | timestamptz | |

**Constraints**: `UNIQUE (channel_id, caller_e164)`; at most 1,000 rows per channel (checked in
service).

## 4. Changes to `calls` (table owned by 003)

| Change | Notes |
|---|---|
| FK `calls.phone_number_id` to `phone_numbers.id` (`ON DELETE RESTRICT`; numbers are soft-deleted) | column created by 003 |
| FK `calls.whatsapp_channel_id` to `whatsapp_channels.id` (`ON DELETE RESTRICT`) | column created by 003 |
| `calls.ring_timeout_s smallint NULL` | outbound only, 10 to 60 |
| `calls.route_detail text NULL` | for example `route_skipped:unpublished_agent`, `inbound_webhook_failed:timeout` |
| index `(phone_number_id) WHERE status IN ('queued','ringing','in_progress')` | active-call count |
| index `(whatsapp_channel_id) WHERE status IN ('queued','ringing','in_progress')` | active-call count |

## 5. Routing functions (SECURITY DEFINER, research R4)

- `route_phone_number(p_number_id text) RETURNS (workspace_id, e164, status,
  inbound_agent_id, inbound_webhook_url)`
- `route_whatsapp_channel(p_channel_id text, p_caller_e164 text) RETURNS (workspace_id, e164,
  status, default_agent_id, route_agent_id, inbound_webhook_url)`
- `lookup_whatsapp_channel_by_verify_hash(p_hash text) RETURNS (channel_id)` and
  `lookup_whatsapp_channel_by_meta_id(p_meta_id text) RETURNS (channel_id, workspace_id)` for the
  unauthenticated webhook endpoints.

Each is `STABLE`, owned by a role with read access to the two tables only, and returns no
secrets. App secrets are then read inside a workspace-scoped transaction.

## 6. Request objects (not persisted beyond the call row)

**OutboundCallRequest**: `to_number` (E.164), `from_number` (E.164 of an active number in the
workspace), `agent_id?`, `dynamic_variables?` (003 rules), `metadata?` (max 4 KB),
`ring_timeout_s?` (10 to 60, default 30). Header `Idempotency-Key` required.

**InboundWebhookReply**: `action` (`answer` default, `decline`), `agent_id?`,
`dynamic_variables?`, `metadata?`; max 16 KB.

## 7. Validation rules (from spec)

- E.164 for every number field; WhatsApp caller ids normalised by prefixing "+".
- Termination address per research R14; `sip:` / `sips:` stripped.
- Labels 1 to 100 chars; verify token 8 to 128 chars; access token and app secret non-empty,
  max 1,024 chars.
- `inbound_allowed_cidrs` valid IPv4 or IPv6 CIDR, max 20.
- Attached agents: same workspace, `published_version_id IS NOT NULL` at attach time.
- Outbound: `to_number != from_number`; from number `active`; rate limit 10/s burst 20.
