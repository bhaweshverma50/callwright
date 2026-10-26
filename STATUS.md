# Status and resume point

Last updated: 2026-10-26. Read this first when resuming.

## Where things stand
- `main` is pushed. Deployed 2026-10-26: Cloud Run API `22810e0` (templates 8 and 9), VM jobs worker `6ff8a42`, VM voice worker `6e1c06d` (greeting plays in full), VM LiveKit server `v1.13.3`, web from `22810e0`. Verified with scripted hosted calls.
- Live app: https://callwright-one.vercel.app (sign up with any email; auto-verified; $5 trial credit). Voice calls work from Test agent on the hosted site only (localhost has no LiveKit).
- Specs 001 done, 002 done except the accessibility audit (T085), 003 live (105 of 118).
- Wave 3a in progress on branches `w3-calls` (spec 006) and `w3-tools` (spec 005), worktrees next to the main clone.

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

## Next, in order
1. Place a hosted test call to confirm the faster greeting and answers (last measured live: greeting 2.1 s, answer 2.7 s). Note: `worker-hint` prints the HEAD tag; pin `CW_API_IMAGE` and `CW_VOICE_IMAGE` to tags that were actually built.
2. Merge wave 3a (`w3-calls`, `w3-tools`), re-chain migrations (both start from `s003_0002`), run all suites, deploy.
3. Wave 3b: specs 004 (flows, uses 005's tool ports) and 010 (channels). Then wave 4 (007, 008) and wave 5 (009).
4. Later: recording service (LiveKit egress; `RECORDINGS_ENABLED=false` today), an object storage bucket (uploads are in memory on Cloud Run), Azure OpenAI in India, key rotation.

## Deploy
See `deploy/cloudrun/README.md` and `deploy/vm/README.md`. Every gcloud command passes the personal account and project explicitly; the machine's default gcloud account belongs to another organisation.
