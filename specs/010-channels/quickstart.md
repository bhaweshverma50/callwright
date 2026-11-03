# Quickstart: Channels

**Feature**: 010-channels | **Plan**: [plan.md](./plan.md)

How to run and check each user story locally. Builds on
[003 quickstart](../003-voice-runtime/quickstart.md): API, jobs worker, voice worker, web app and
a LiveKit server must already be running.

## 1. Extra prerequisites

- LiveKit SIP: a LiveKit Cloud project with SIP enabled, or the self-hosted `livekit/sip`
  container next to `livekit-server`. livekit-sip finds the server through Redis, so
  `livekit-server` needs a `redis:` block in its config (`--dev` alone keeps state in memory and
  never sees the SIP service). `services/api/tests/e2e/sipp/run.sh up` starts livekit-sip
  against a local server (README.md next to it).
- A SIP client for test calls: SIPp (scripted) or a softphone such as Linphone.
- For WhatsApp (US4 to US5): a Meta developer app with a WhatsApp Business test number, its
  access token and app secret, and a public HTTPS tunnel to the API (for example `cloudflared`).

```bash
# services/api/.env
LIVEKIT_SIP_HOST=localhost:5060            # or <project>.sip.livekit.cloud
WEBHOOKS_ALLOW_HTTP=true                   # section 9: a local http receiver (dev only)
WEBHOOKS_ALLOW_PRIVATE=true
WHATSAPP_GRAPH_BASE_URL=https://graph.facebook.com
WHATSAPP_GRAPH_API_VERSION=v23.0
OUTBOUND_RATE_PER_SECOND=10
OUTBOUND_RATE_BURST=20
INBOUND_WEBHOOK_TIMEOUT_S=3
```

```bash
cd services/api && uv run alembic upgrade head      # applies s010_0001_channels
```

## 2. User Story 1: import a number

UI: `/phone-numbers`, "Import number", enter `+14155550100`, label "Main Office Line",
termination `sip:trunk.example-carrier.com:5060`. The saved address shows without `sip:`.

API:

```bash
curl -s -X POST localhost:8100/v1/phone-numbers -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"e164":"+14155550100","label":"Main Office Line","termination_address":"trunk.example-carrier.com:5060"}' | jq
curl -s localhost:8100/v1/phone-numbers/sip-settings -H "Authorization: Bearer $JWT" | jq
```

Expect `status: "active"` and `has_auth_password: false`. A body with an extra field is refused:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8100/v1/phone-numbers -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"e164":"+14155550101","label":"X","termination_address":"trunk.example-carrier.com","user_id":"usr_x"}'   # 422
```

In the browser, pressing "Import number" on the empty form shows a message under number, label
and termination address and sends nothing; the sidebar entry and page title both read
"Channels".

Check LiveKit objects (`lk` reads `LIVEKIT_URL=http://localhost:7880`, `LIVEKIT_API_KEY` and
`LIVEKIT_API_SECRET` from the environment, or pass `--url --api-key --api-secret`):

```bash
lk sip inbound list && lk sip outbound list && lk sip dispatch list   # no dispatch rule yet
```

## 3. User Story 1: answer an inbound call

The agent must be published first (otherwise 422 `agent_not_published`).

```bash
curl -s -X PATCH localhost:8100/v1/phone-numbers/num_... -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{"inbound_agent_id":"agt_..."}' | jq .status
lk sip dispatch list                                                   # one rule, metadata route_ref num_...
```

Place a call to `sip:+14155550100@$LIVEKIT_SIP_HOST` from a softphone (or
`services/api/tests/e2e/sipp/run.sh inbound_answer`, section 6). The call row shows `ringing`
for the agent's ring duration, then the greeting. livekit-sip answers 200 OK as soon as the room
is joined, so the caller hears silence (not ringback) during the ring phase. Then:

```bash
psql $DATABASE_URL -c "select channel, from_number, to_number, phone_number_id, status,
  disconnect_reason from calls order by created_at desc limit 1;"
```

Detach the agent (`{"inbound_agent_id": null}`) and call again: livekit-sip refuses the call
(486, no dispatch rule) and no new row appears in `calls`.

## 4. User Story 2: outbound call

The default calling hours are 09:00 to 21:00 in the recipient's zone (`America/Los_Angeles` for
`+1415...`); outside them every request below is blocked with `outside_calling_hours`, so run it
in those hours or add `"recipient_timezone":"<a zone where it is daytime>"` to the bodies. The
example termination address does not exist, so the admitted call ends `failed`.

```bash
curl -s -X POST localhost:8100/v1/outbound-calls -H "Authorization: Bearer $JWT" \
  -H "Idempotency-Key: demo-0001" -H "Content-Type: application/json" \
  -d '{"to_number":"+14155550199","from_number":"+14155550100","dynamic_variables":{"customer_name":"Asha"}}' | jq
# run the same command again: same call_id, "idempotent_replay": true
```

Compliance (spec FR-034 to FR-038). Add the destination to the do-not-call list and retry with a
new key; the request is blocked with `dnc_listed` and no call is created:

```bash
curl -s -X POST localhost:8100/v1/dnc-entries -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{"number":"(415) 555-0199","default_region":"US"}' | jq
# -> {"id":"dnc_...","number":"+14155550199","source":"manual",...}
curl -s -X POST localhost:8100/v1/outbound-calls -H "Authorization: Bearer $JWT" \
  -H "Idempotency-Key: demo-0002" -H "Content-Type: application/json" \
  -d '{"to_number":"+14155550199","from_number":"+14155550100"}' | jq
# -> 422, "reason":"dnc_listed"
curl -s -F file=@dnc.csv -F default_region=US localhost:8100/v1/dnc-entries/import \
  -H "Authorization: Bearer $JWT" | jq      # imported, duplicates, invalid rows
```

Remove the entry (`DELETE /v1/dnc-entries/<dnc_id>`), then make today's window exclude the
recipient's local time and retry:

```bash
curl -s -X PUT localhost:8100/v1/outbound-calling-hours -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"windows":{"mon":null,"tue":null,"wed":null,"thu":null,"fri":null,"sat":null,"sun":null}}' | jq
# retry the outbound call: 422, "reason":"outside_calling_hours", with recipient_timezones,
# recipient_local_time and next_allowed_at; passing "recipient_timezone":"America/New_York"
# evaluates in that zone instead
curl -s "localhost:8100/v1/outbound-policy-decisions" -H "Authorization: Bearer $JWT" | jq
psql $DATABASE_URL -c "select count(*) from calls where to_number = '+14155550199' and created_at > now() - interval '5 minutes';"
# expect only the call from the first command; blocked attempts create no call and no charge
```

Restore the defaults by sending 09:00 to 21:00 for every day.

Busy and no-answer outcomes without a carrier:

```bash
cd services/voice-worker && uv run pytest tests/harness -k "outbound"
```

## 5. User Story 3: edit and delete safely

1. Start an inbound call and keep it open.
2. `DELETE /v1/phone-numbers/num_...` returns 409 with `active_call_count: 1`.
3. `DELETE /v1/phone-numbers/num_...?when_idle=true` returns 202 with `status: "draining"`;
   a second inbound call is refused; an outbound request returns 409 `from-number-not-active`.
4. Hang up the first call. Within about a minute (the drain cron) the number disappears from
   the list and `lk sip inbound list` no longer shows its trunk. The ended call still shows the
   number.

## 6. Optional SIPp end-to-end

Setup (livekit-sip, the two numbers, `CALLWRIGHT_TOKEN`) is in
`services/api/tests/e2e/sipp/README.md`.

```bash
services/api/tests/e2e/sipp/run.sh up               # livekit-sip next to the local LiveKit
services/api/tests/e2e/sipp/run.sh inbound_answer   # dials the number, 8 s of G.711 RTP, BYE
services/api/tests/e2e/sipp/run.sh outbound_busy    # SIPp answers 486: the call ends busy, unbilled
SIPP_E2E=1 uv run --directory services/api pytest tests/e2e -q   # both, through pytest
```

## 7. User Story 4: WhatsApp channel

Without a Meta app, `WHATSAPP_GRAPH_MODE=fake` on the API checks the API side locally: creating
the channel skips Meta, Meta's verification request can be replayed with
`curl "localhost:8100/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=callwright-dev-verify&hub.challenge=42"`
(the channel turns `active`), and steps 5 and section 8 work as written. Real calls need Meta.

1. Expose the API: `cloudflared tunnel --url http://localhost:8100`; set the public base URL so
   `GET /v1/whatsapp/settings` shows `https://<tunnel>/v1/whatsapp/webhook`.
2. Create the channel:

```bash
curl -s -X POST localhost:8100/v1/whatsapp/channels -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{
    "meta_phone_number_id":"123456789012345","e164":"+15550001111","label":"Support WA",
    "access_token":"'$WA_TOKEN'","verify_token":"callwright-dev-verify","app_secret":"'$WA_APP_SECRET'"}' | jq
```

Expect `status: "setup_incomplete"`, `credentials_verified_at` and `calling_enabled_at` set.
3. In the Meta app dashboard, set the callback URL and verify token `callwright-dev-verify`,
   subscribe to `calls`. Expect `status: "active"` and `webhook_verified_at` set.
4. Attach an agent (`PATCH ... {"inbound_agent_id":"agt_..."}`), call the business number from
   WhatsApp on a phone. The call row shows channel `whatsapp` and the caller's number in E.164.
5. Forged notification check:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8100/v1/whatsapp/webhook \
  -H "X-Hub-Signature-256: sha256=$(printf 0%.0s {1..64})" -H "Content-Type: application/json" \
  -d '{"object":"whatsapp_business_account","entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"123456789012345"}}}]}]}'
# expect 401
```

## 8. User Story 5: caller routes

```bash
curl -s -X POST localhost:8100/v1/whatsapp/channels/wa_.../caller-routes \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"caller_number":"919800000001","agent_id":"agt_X"}' | jq .caller_number   # "+919800000001"
```

Call from that WhatsApp account: agent X answers; another account reaches the default agent.

## 9. User Story 6: inbound webhook

```bash
uv run --directory services/api python tests/integration/tools/flaky_receiver.py --fail 0 \
  --port 9010 --reply '{"dynamic_variables":{"customer_name":"Asha"}}'
curl -s -X PATCH localhost:8100/v1/phone-numbers/num_... -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{"inbound_webhook_url":"http://127.0.0.1:9010/inbound"}'
```

(Use `http://host.docker.internal:9010` when the API runs in Docker.) Call the number: an agent
whose greeting is `Hi {{customer_name}}` says "Hi Asha". Stop the receiver and call again: the
agent uses the default value and `calls.route_detail` reads `inbound_webhook_failed:unreachable`.
