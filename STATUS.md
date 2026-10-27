# Status and resume point

Last updated: 2026-10-27. Read this first when resuming.

## Where things stand
- `main` is pushed and deployed (2026-10-26, wave 3 live): Cloud Run API `7ef3756` (migrations through s006_0002), VM jobs worker `7ef3756`, VM voice worker `cf4bea6`, VM LiveKit `v1.13.3`, web from `7ef3756`. Verified on the hosted app with scripted calls: silence check-ins end the call as inactivity, a flow agent call, and the assistant answering "what did my last call cost?".
- Live app: https://callwright-one.vercel.app (sign up with any email; auto-verified; $5 trial credit). Voice calls work from Test agent on the hosted site only (localhost has no LiveKit).
- Specs 001 done, 002 done except the accessibility audit (T085), 003 live (105 of 118).
- Wave 3 complete 2026-10-26: specs 004 (114/114), 005 (99/100), 006 (95/95), 010 (83/85). 701 of 964 tasks. Follow-up fixes merged: flow builder performance and layout, Ask assistant call lookups and push-to-talk, compact dock, silence check-ins (worker), version compare, tabs, call panel layout. Migrations chain s006_0001, s010_0001, s004_0001, s006_0002. Suites: API 1430, worker 468, web 201. Telephony stays fake until `LIVEKIT_SIP_HOST` is set (deploy/vm/README.md). Deleting an agent attached to a number is refused (409 agent_in_use).
- Wave 3a merged and deployed on 2026-10-26: spec 005 tools and knowledge (99 of 100 tasks; T092 quickstart run open) and spec 006 calls and analytics (95 of 95). Migrations chain s003_0002, s005_0001, s006_0001. Suites on the merge: API 1091, worker 385, web 145.

## Voice speed (done 2026-10-26, merged)
Real-vendor live benchmark (`tests/harness/bench`, caller-measured, Deepgram Nova-3, gpt-5.1, ElevenLabs Flash, run from India):

| Change | Answer p50 | Answer p95 | Caller cut-offs |
|---|---|---|---|
| Baseline | 1960 ms | 3062 ms | 3 |
| Priority tier, session and greeting ready before the caller joins | 1778 ms | 2580 ms | 1 |
| Plus short first sentence instruction | 1658 ms | 2207 ms | 0 |
| Deepgram Flux with eager end of turn | 1636 ms | 2169 ms | 0 |

- GPT-5.1 already runs with `reasoning_effort: none` (LiveKit plugin default), so no reasoning setting was needed.
- `OPENAI_SERVICE_TIER=priority` (VM default in render-env.sh) cuts time to first token from about 970 to 700 ms at twice the token price.
- Flux is not worth switching the default to: the gain at the caller is within noise.
- The remaining floor is the network round trip to OpenAI from India (about 550 ms). The next big step is an Azure OpenAI deployment in an Indian region (the `azure_openai` provider is already the default and used when Azure secrets exist).
- Spoken filler before tools and "still checking" belong to spec 005 (tools), briefed to the `w3-tools` build.

## Hosted call fix (2026-10-26)
- Calls ended after one reply with the timer stuck at 0:00. Cause: LiveKit server 1.8.4 on the VM is too old for livekit-client 2.22; once the agent joined before the caller, the browser's publish negotiation timed out, the client did a full reconnect (leave and rejoin), and the worker treated the leave as a hang-up. Fixed by LiveKit 1.13.3 (verified with a scripted hosted call) and by marking the call live once the room is joined.
- `apps/web/scripts/e2e-call.mjs` places a real browser test call with a fake microphone (`API=... WEB=... node scripts/e2e-call.mjs caller.wav out-dir [template]`); defaults target the local stack.
- Follow-up: the worker hangs up as soon as the caller's participant leaves; a short rejoin grace would survive network blips but must not bill the grace seconds.

## Telephony lab (2026-10-27, not deployed)
- Real SIP without a carrier: Asterisk `lab-pbx` service on the VM (deploy/vm/lab-pbx, compose profile `lab`) stands in for the phone company. Softphones `phone1`/`phone2` register on 5080 and call Callwright numbers through livekit-sip; Callwright's outbound calls ring them (last digit picks the phone). No public phone network, no per-minute cost, idle shutdown kept.
- Verified locally with the real images in one network namespace: inbound opens a `call-in-` room with the SIP participant; outbound rings a registered phone with the number as caller id and returns 486 busy / 480 unavailable. Not yet verified: RTP across the VM's public IP and a voice agent answering (needs the deploy).
- Fixed on the way: the compose `sip` service mounted its config where livekit/sip v1.2.0 never reads it (the entrypoint forces `--config=/sip/config.yaml`), so it would not have started. SIP over TLS is now only configured once certificates exist.
- `render-env.sh` and `deploy.sh` now keep `LIVEKIT_SIP_HOST` (and the lab flag) across renders and deploys instead of silently dropping them.
- To turn on: deploy/vm/README.md, "Lab mode" (DNS `sip`, firewall rule `callwright-lab-pbx`, render with `CW_LIVEKIT_SIP_HOST=sip.bhawesh.dev CW_LAB_PBX=true`, API deploy with `LIVEKIT_SIP_HOST`, import `+919000000100` with termination `127.0.0.1:5080`). Then T067 (SIPp scenarios) and T069 (channels quickstart run) can be done against it.

## Call fixes from the first lab SIP call (2026-10-27, not deployed)
- Agent never hung up: single-prompt agents had no end_call tool unless one was attached. Now every single-prompt agent gets a built-in `end_call` (unless it has its own), a prompt line to call it in the goodbye reply without waiting for the caller, and a worker safety net that hangs up 2 s after a reply ending in a goodbye (cancelled if the caller speaks). end_call waits for the goodbye to finish playing before hanging up (it used to cut it off). The preset's spoken goodbye line is now empty by default (it doubled the goodbye).
- Agent transcript lines start at the turn's first audio (they were stamped when playout ended). Turns whose caller speech voice detection missed now get a latency from the final transcript time instead of "n/a".
- Vendor plugins are imported in prewarm (a 2.6 s event-loop stall at call start). "85% heard" reads "85% sure" (it is STT confidence).
- Dashboard: sparkline dot was stretched into an oval and the line stopped short (pathLength with a non-scaling stroke); copilot dock mic is now a soft secondary button with a divider before "Ask about your data".
- Sentiment shows "Unknown" because post-call analysis is spec 007 (not built; pipeline step `analyze` is skipped).

## Next, in order
1. Place a hosted test call to confirm the faster greeting and answers (last measured live: greeting 2.1 s, answer 2.7 s). Note: `worker-hint` prints the HEAD tag; pin `CW_API_IMAGE` and `CW_VOICE_IMAGE` to tags that were actually built.
2. Wave 3a is live. Notes: new secrets need `deploy.sh ... setup` before `api` (it grants the API service account access); the dashboard counts live calls only. New optional env: `ANALYTICS_CHAT_MODEL`, `VOICE_COMMAND_MODEL`, `RECORDING_URL_TTL_S`, `SIP_OUTBOUND_TRUNK_ID`; `DEEPGRAM_API_KEY` now mounted on the API. Uploads stay in memory (`STORAGE_MODE=fake`) until a bucket exists.
3. Wave 3b: specs 004 (flows, uses 005's tool ports) and 010 (channels). Then wave 4 (007, 008) and wave 5 (009).
4. Later: recording service (LiveKit egress; `RECORDINGS_ENABLED=false` today), an object storage bucket (uploads are in memory on Cloud Run), Azure OpenAI in India, key rotation.

## Deploy
See `deploy/cloudrun/README.md` and `deploy/vm/README.md`. Every gcloud command passes the personal account and project explicitly; the machine's default gcloud account belongs to another organisation.
