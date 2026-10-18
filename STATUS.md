# Status and resume point

Last updated: 2026-10-18. Read this first when resuming.

## Where things stand
- `main` is pushed and deployed: Cloud Run API, VM jobs worker and VM voice worker all run image tag `6ff8a42`.
- Live app: https://callwright-one.vercel.app (sign up with any email; auto-verified; $5 trial credit). Voice calls work from Test agent on the hosted site only (localhost has no LiveKit).
- Progress: 310 of 964 tasks. Spec 001 done, 002 done except the accessibility audit (T085), 003 live (105 of 118).
- First hosted call: greeting 2.1 s after join, answer 2.7 s after the caller stops, charged $0.041.

## Next, in order
1. Voice speed. Branch `voice-speed` holds only a live benchmark harness. To build: no reasoning for GPT-5 on normal turns (plus an agent `llm.reasoning` setting), a spoken filler before every tool, knowledge or HTTP call and a "still checking" line after about 3 s, a 700 ms backchannel from pre-synthesised clips, a pre-synthesised greeting, Deepgram Flux evaluation for English, and warm vendor connections. Target about 1.0 to 1.3 s to the answer; measure with real calls before and after.
2. Fix the Test agent page copy: calls do not land in call history until spec 006.
3. Wave 3: specs 004, 005, 006 (call history read API is missing), 010. Then wave 4 (007, 008) and wave 5 (009).
4. Later: recording service (LiveKit egress; `RECORDINGS_ENABLED=false` today), an object storage bucket (uploads are in memory on Cloud Run), key rotation.

## Deploy
See `deploy/cloudrun/README.md` and `deploy/vm/README.md`. Every gcloud command passes the personal account and project explicitly; the machine's default gcloud account belongs to another organisation.
