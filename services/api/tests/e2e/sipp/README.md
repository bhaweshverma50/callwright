# SIPp end-to-end scenarios (010 T067)

Optional checks that put real SIP signalling and RTP through livekit-sip, LiveKit and the voice
worker. They are skipped unless `SIPP_E2E=1`, so CI never runs them.

| Scenario | SIPp plays | Expected |
|---|---|---|
| `inbound_answer.xml` | a carrier calling a Callwright number | 100/180, 200 OK after the agent's ring phase, ACK, 8 s of G.711 A-law RTP (`/sipp/g711a.pcap` from the image), BYE answered 200; a `sip_inbound` call row for the number ending `user_hangup` |
| `outbound_busy.xml` | the carrier at a number's termination address | livekit-sip's INVITE answered 100, 180, then 486 Busy Here and ACKed; the call ends `busy` with diagnostic `sip_486` and no charge |

`run.sh` runs SIPp from the official image, pinned by digest
(`ctaloi/sipp@sha256:c459f234...`, SIPp 3.5.1, amd64 only, emulated on arm64), inside the
livekit-sip container's network namespace. That mirrors the VM, where livekit-sip, the lab PBX and
LiveKit share the host network: SIPp reaches livekit-sip on `127.0.0.1:5060` and livekit-sip
reaches SIPp on `127.0.0.1:5090`. SIPp is the carrier here, so the lab PBX (Asterisk) is not
needed; it sits on the same path on the VM (deploy/vm/README.md, "Lab mode").

## Setup

1. Local stack from the [003 quickstart](../../../../../specs/003-voice-runtime/quickstart.md):
   Postgres and Redis (`make up`), a LiveKit server **with Redis** (livekit-sip finds LiveKit
   through it), the API and jobs worker with `LIVEKIT_SIP_HOST=localhost:5060`, and a voice
   worker. Without vendor keys use the fake-vendor worker (same agent server and job entry, fake
   STT, LLM and TTS):

   ```bash
   # livekit.yaml: port 7880, keys {devkey: secret}, redis {address: localhost:56379},
   # webhook {api_key: devkey, urls: [http://localhost:8100/v1/livekit/webhook]}
   livekit-server --config livekit.yaml
   cd services/voice-worker && PYTHONPATH=. uv run python -c "
   import asyncio
   from worker.entry import create_server
   from worker.settings import WorkerSettings
   from tests.harness.bench.live_worker import bench_job_entry
   if __name__ == '__main__':
       asyncio.run(create_server(WorkerSettings(), entrypoint=bench_job_entry).run(devmode=True))"
   ```

2. livekit-sip next to it (writes a config pointing at the host's LiveKit and Redis):

   ```bash
   LIVEKIT_WS=ws://host.docker.internal:7880 SIP_REDIS=host.docker.internal:56379 \
     services/api/tests/e2e/sipp/run.sh up
   ```

3. In Callwright (API or the Channels page), with a published agent:
   * number `+14155550100`, any termination address, inbound agent set (`inbound_answer`);
   * number `+14155550110`, termination `127.0.0.1:5090`, transport `udp`, outbound agent set
     (`outbound_busy`). The destination defaults to `+919000000001`, so the default 09:00 to
     21:00 calling hours are judged in India time; pick another `SIPP_TO` if that is outside them.

## Run

```bash
export CALLWRIGHT_API=http://localhost:8100/v1 CALLWRIGHT_TOKEN=<access token>
services/api/tests/e2e/sipp/run.sh inbound_answer
services/api/tests/e2e/sipp/run.sh outbound_busy
# or both through pytest
SIPP_E2E=1 uv run --directory services/api pytest tests/e2e -q
services/api/tests/e2e/sipp/run.sh down
```

Settings: `SIP_CONTAINER` (default `callwright-sip-e2e`), `SIP_IMAGE`, `SIPP_IMAGE`,
`SIPP_NUMBER`, `SIPP_FROM`, `SIPP_TO`, `SIP_REDIS_DB`, `SIPP_CALL_TIMEOUT_S`.

## Not covered

* Media across a public IP and NAT (the VM's firewall and `use_external_ip`): only the VM shows
  that (deploy/vm/README.md, "Lab mode", step 6).
* SIP over TLS and SRTP (WhatsApp): needs certificates and Meta.
* livekit-sip answers 200 OK as soon as the room is joined; the agent's ring phase then runs
  behind an answered call, so the caller hears silence rather than ringback for the ring
  duration (billing still starts at `in_progress`).
