# Quickstart run: Channels (T069)

Run on 2026-11-03 on the local stack of the [003 run](../003-voice-runtime/quickstart-results.md)
(API on 8150 with `LIVEKIT_SIP_HOST=localhost:5060`, LiveKit 1.13.3 with Redis, fake-vendor voice
worker) plus `livekit/sip:v1.2.0` in Docker and SIPp 3.5.1 in its network namespace
(`services/api/tests/e2e/sipp`, T067). Real SIP signalling and G.711 RTP went through
livekit-sip into LiveKit rooms and the voice worker.

| Section | Result | Notes |
|---|---|---|
| 1 Prerequisites | drift | Migration is `s010_0001_channels`, not `0010_channels`; API port 8100, not 8000. livekit-sip only works with a LiveKit server that has Redis (noted). |
| 2 Import a number | pass | `status: active`, `has_auth_password: false`; extra field 422; `sip-settings` `telephony_enabled: true`; one inbound and one outbound trunk, no dispatch rule. A `sip:` prefix is stored without it. Browser (Playwright): heading and sidebar read "Channels"; the empty Import form shows a message under number, label and termination address and sends no request. |
| 3 Inbound call | drift | Attaching an unpublished agent is 422 `agent_not_published` (doc now says publish first). Dispatch rule with `callwright-voice`. SIPp call: 100, 180, 200, ACK, 8 s RTP, BYE; row `sip_inbound`, from `+15551230000`, to the number, `phone_number_id` set, `ringing` for the 5 s ring duration, greeting, `user_hangup`, 4 s billed. livekit-sip sends 200 OK about 1.4 s after the INVITE, so the ring phase runs behind an answered call (silence, not ringback); recorded in the doc. Detached: livekit-sip answers 486 and no row is written. |
| 4 Outbound | drift | Run at 22:30 Los Angeles time, so the doc's first request was blocked `outside_calling_hours`; with `recipient_timezone` it was admitted and the replay returned the same `call_id` with `idempotent_replay: true`. DNC add (normalised to `+14155550199`), `dnc_listed` 422, CSV import `rows 4, imported 2, duplicates 1, invalid 1` (row 4), remove, all-days-off window gives `outside_calling_hours` with zones, local time and `next_allowed_at`; decisions listed; one call in the window. Restored 09:00 to 21:00. Harness `-k outbound` 2 passed. Doc notes the calling hours. |
| 5 Edit and delete | drift | With a SIPp call held open (looping RTP): DELETE 409 `number_has_active_calls`, `active_call_count: 1`; `?when_idle=true` 202 `draining`; a second inbound call refused (486); outbound 409 `from_number_not_active`. After the hang-up the number was gone in about 36 s and its trunk removed; the ended call keeps the number. Doc now says "within about a minute" (drain cron). |
| 6 SIPp | pass | New (T067): `run.sh inbound_answer` and `run.sh outbound_busy` pass, also through `SIPP_E2E=1 pytest tests/e2e` (2 passed). Outbound: SIPp at the termination address answers 100, 180, 486; the call ends `busy`, diagnostic `sip_486`, no charge. |
| 7 WhatsApp | partial | Real Meta not run (needs a Meta app, a business number and a public tunnel). With `WHATSAPP_GRAPH_MODE=fake`: channel created `setup_incomplete` with `credentials_verified_at` and `calling_enabled_at`; a replayed verification request returns the challenge and the channel turns `active`; the forged notification gets 401. Doc notes the fake mode. |
| 8 Caller routes | partial | Route created, `caller_number` normalised to `+919800000001`. Calls from WhatsApp not run (Meta). |
| 9 Inbound webhook | drift + test tool fix | `flaky_receiver.py` had no `--reply` option: added (`--reply JSON`, output flushed). The doc's `host.docker.internal` URL only fits an API in Docker; local runs use `127.0.0.1` (needs `WEBHOOKS_ALLOW_HTTP/PRIVATE`). Receiver up: the agent says "Hi Asha". Receiver down: "Hi there" and `route_detail` `inbound_webhook_failed:unreachable` (the doc said `connection_error`; the code's reason name is kept). |

Not covered locally: RTP across the VM's public IP and NAT, SIP over TLS and SRTP, WhatsApp
calls, and a voice agent with real vendors on a SIP call.
