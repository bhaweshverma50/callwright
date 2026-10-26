# Status and resume point

Last updated: 2026-10-26. Read this first when resuming.

## Where things stand
- `main` is pushed. Deployed: Cloud Run API and VM jobs worker at image tag `6ff8a42`; VM voice worker still at `6ff8a42`. The voice worker image `62c172c` (voice speed work) is built and pushed to Artifact Registry but NOT rolled out to the VM yet; the web copy fix is not deployed to Vercel yet.
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

## Next, in order
1. Roll out: `deploy/cloudrun/deploy.sh callwright-dev bhaweshverma50@gmail.com worker-hint` and run the printed VM commands with `CW_VOICE_IMAGE` at `62c172c` (or the merge tag after wave 3a); `cd apps/web && vercel deploy --prod --scope bhaweshverma50s-projects`.
2. Merge wave 3a (`w3-calls`, `w3-tools`), re-chain migrations (both start from `s003_0002`), run all suites, deploy.
3. Wave 3b: specs 004 (flows, uses 005's tool ports) and 010 (channels). Then wave 4 (007, 008) and wave 5 (009).
4. Later: recording service (LiveKit egress; `RECORDINGS_ENABLED=false` today), an object storage bucket (uploads are in memory on Cloud Run), Azure OpenAI in India, key rotation.

## Deploy
See `deploy/cloudrun/README.md` and `deploy/vm/README.md`. Every gcloud command passes the personal account and project explicitly; the machine's default gcloud account belongs to another organisation.
