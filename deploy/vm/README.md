# Realtime VM (GCP, asia-south1)

`callwright-rtc` (e2-medium, static IP 34.180.13.164, project `callwright-dev`) runs Caddy (TLS for
`rtc.bhawesh.dev`), LiveKit server, Redis, the jobs worker and the voice worker via
`docker-compose.yml`. Secrets live in Secret Manager (`REDIS_PASSWORD`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`, the worker secrets and vendor keys below); `render-env.sh` writes `.env`,
`worker.env`, `voice.env` and `livekit.yaml` on the VM (mode 600). Never commit rendered files.

Firewall: `callwright-rtc-public` allows tcp 80, 443, 7881 and udp 50000-50200 from anywhere;
`callwright-rtc-internal` allows tcp 6379 (Redis) only from internal VPC ranges, used by Cloud Run
through Direct VPC egress.

DNS: Cloudflare record `rtc` A 34.180.13.164, DNS only (not proxied: the proxy breaks WebRTC).

Update: copy files with `gcloud compute scp ... --account bhaweshverma50@gmail.com --project callwright-dev`,
then on the VM `cd /opt/callwright && ./render-env.sh && sudo docker compose up -d`.

## Voice worker

Service `voice` in `docker-compose.yml` runs the voice worker image
(`asia-south1-docker.pkg.dev/callwright-dev/callwright/voice-worker:<git sha>`, built from
`services/voice-worker/Dockerfile` by `deploy/vm/cloudbuild-voice.yaml`). It registers with
LiveKit on `ws://127.0.0.1:7880` as agent `callwright-voice`, claims each dispatched call from the
API at `$CW_API_BASE_URL/v1/internal` with `SERVICE_TOKEN`, and talks to the vendors directly. The
turn detector models are baked into the image, so a call never waits on a download. Health:
`curl -s -o /dev/null -w '%{http_code}\n' localhost:8190` answers 200.

`render-env.sh` writes `voice.env` (mode 600): LiveKit URL and keys, the internal API URL
(`CW_API_BASE_URL`, default the Cloud Run URL), `CALLWRIGHT_SERVICE_TOKEN` from `SERVICE_TOKEN`,
`CALLWRIGHT_OTEL_EXPORTER=none`, the agent server size (`WORKER_NUM_IDLE_PROCESSES=2`,
`WORKER_LOAD_THRESHOLD=0.9`; override with `CW_VOICE_IDLE_PROCESSES`, `CW_VOICE_LOAD_THRESHOLD`)
and each vendor key that exists in Secret Manager: `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`,
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `ELEVENLABS_API_KEY` (written as
`ELEVEN_API_KEY`, the name the ElevenLabs plugin reads), `CARTESIA_API_KEY`, `ASSEMBLYAI_API_KEY`,
`SARVAM_API_KEY`, `FISHAUDIO_API_KEY`, `SANAS_API_KEY`, `AI_COUSTICS_API_KEY`. The VM service account
needs `roles/secretmanager.secretAccessor` on each of them (`deploy.sh setup` grants it for the
secrets that exist).

LLM provider: agents choose it with `llm.provider` in their config. The default and the launch
templates use `azure_openai`; when Azure OpenAI is not configured (no `AZURE_OPENAI_API_KEY` or
`AZURE_OPENAI_ENDPOINT`) and `OPENAI_API_KEY` is, the worker runs the same model (`gpt-5.1`,
`gpt-5.2`, `gpt-5-mini`) on OpenAI and records an `llm_provider_fallback` warning on the call. An
agent can also select `{"provider": "openai", "model": "gpt-5.1"}` in the editor. Both providers
have the same price.

Recording: there is no LiveKit egress service on this VM, so calls cannot be recorded. Run the API
and the jobs worker with `RECORDINGS_ENABLED=false` (deploy.sh and render-env.sh set it), which
admits every call with recording off (`recording_status=not_recorded`). If it is left on, the
recording start fails within 20 seconds, the call keeps running, and the call shows
`recording_status=failed` with a `recording_unavailable` processing warning.

### Roll out a new voice worker image

Every command names the account and project. Build (Cloud Build, tag = git short sha):

```bash
deploy/cloudrun/deploy.sh callwright-dev bhaweshverma50@gmail.com build-voice
deploy/cloudrun/deploy.sh callwright-dev bhaweshverma50@gmail.com worker-hint   # prints the steps below
```

Then, with `TAG` the same git short sha (start the VM first if it is off:
`gcloud compute instances start callwright-rtc --zone asia-south1-a --account bhaweshverma50@gmail.com --project callwright-dev`):

```bash
ACCOUNT=bhaweshverma50@gmail.com; PROJECT=callwright-dev; ZONE=asia-south1-a
API_IMAGE=asia-south1-docker.pkg.dev/$PROJECT/callwright/api:$TAG
VOICE_IMAGE=asia-south1-docker.pkg.dev/$PROJECT/callwright/voice-worker:$TAG
gcloud compute scp deploy/vm/docker-compose.yml deploy/vm/render-env.sh deploy/vm/livekit.yaml.tmpl callwright-rtc:/opt/callwright/ \
  --zone $ZONE --account $ACCOUNT --project $PROJECT
gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
  "cd /opt/callwright && CW_API_IMAGE=$API_IMAGE CW_VOICE_IMAGE=$VOICE_IMAGE ./render-env.sh \
   && sudo docker compose pull worker voice && sudo docker compose up -d worker voice"
gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
  "curl -s -o /dev/null -w 'voice %{http_code}\n' localhost:8190; sudo docker compose -f /opt/callwright/docker-compose.yml logs --tail 30 voice"
```

The first roll-out also changes `livekit.yaml.tmpl` (a loopback ICE candidate so the voice worker's
media stays on the host); restart LiveKit once after rendering, while no call is running:
`sudo docker compose restart livekit`.

`render-env.sh` keeps the pinned `VOICE_IMAGE` (and `API_IMAGE`) in `.env` across later renders,
so a reboot or a plain `sudo docker compose up -d` runs the same images. The log should show the
worker registering (`registered worker`) with the LiveKit server. Then place a browser test call
from the agent editor ("Test agent").

## Jobs worker

The arq jobs worker runs here (service `worker` in `docker-compose.yml`): the API image built by
`deploy/cloudrun` (`asia-south1-docker.pkg.dev/callwright-dev/callwright/api`), started with
`ROLE=worker`. It reads `worker.env`, which `render-env.sh` writes from Secret Manager: the same
database URLs and secrets as the Cloud Run API (`DATABASE_URL`, `DATABASE_ADMIN_URL`,
`AUTH_JWT_SECRET`, `SECRETS_MASTER_KEY`, `SERVICE_TOKEN`, `STRIPE_WEBHOOK_SECRET`, optional vendor
keys), Redis on `127.0.0.1`, and LiveKit on `ws://127.0.0.1:7880`. Non-secret values have demo
defaults and can be overridden (`CW_ENV`, `CW_WEB_BASE_URL`, `CW_API_BASE_URL`, `CW_STRIPE_MODE`,
`CW_AUTH_PROVIDER`, `CW_ARQ_POLL_DELAY_S`); keep them equal to the Cloud Run API's settings.

One-time VM setup for pulling the image (the VM service account needs
`roles/artifactregistry.reader` on the repository and `roles/secretmanager.secretAccessor`):

```bash
sudo gcloud auth configure-docker asia-south1-docker.pkg.dev --quiet
```

After a new image is pushed: `cd /opt/callwright && sudo docker compose pull worker && sudo docker compose up -d worker`
(or follow "Roll out a new voice worker image" below, which pins and rolls both workers).
Health: `curl -s localhost:8191` answers `{"status":"ok","role":"worker"}`.

## Idle shutdown and wake on demand

The VM powers itself off after 15 idle minutes and the API starts it again when needed.

* `idle-shutdown.sh` runs every minute (`callwright-idle.timer`). Idle means all of: no LiveKit
  room with participants, an empty arq queue with no job in progress (periodic cron housekeeping
  is ignored), and no API request for 15 minutes (`cw:last_api_activity`, written by the API at
  most every 30 s). When that holds for 15 consecutive minutes it runs `shutdown -h now`. A check
  that cannot be read counts as busy. Nothing happens in the first 10 minutes after boot.
* Keep the VM up for maintenance: `sudo touch /opt/callwright/keep-awake` (remove it afterwards).
* Decisions: `journalctl -t callwright-idle -f` (one line per minute: `busy: ...`,
  `idle for Ns ...`, `powering off`). Try it without powering off:
  `sudo DRY_RUN=1 /opt/callwright/idle-shutdown.sh`.
* Wake: when the API cannot reach Redis it answers 503 `waking_up` and calls the Compute Engine
  `instances.start` API for this VM (WAKE_VM_* settings and IAM in `deploy/cloudrun/README.md`).
  Docker and every compose service start on boot, so the stack is back in about a minute; the web
  app shows "Starting servers" meanwhile and retries on its own.

Install (once, and again after changing the unit files):

```bash
cd /opt/callwright && sudo ./install-idle.sh
```

It enables docker and containerd at boot, checks that every compose service has
`restart: unless-stopped`, and enables the timer. It needs `curl`, `openssl` and `python3`
(present on the Debian images).

Copy the new files with the existing scp step: `docker-compose.yml`, `render-env.sh`,
`idle-shutdown.sh`, `install-idle.sh` and `systemd/`.

## Telephony: phone numbers and WhatsApp (spec 010, not deployed)

The API ships phone numbers, outbound calls and WhatsApp channels, but this VM runs no SIP
service yet. Until it does, `LIVEKIT_SIP_HOST` is unset: the API keeps SIP trunks and dispatch
rules in memory (`SIP_MODE=auto`), WhatsApp setup does not call Meta (`WHATSAPP_GRAPH_MODE=auto`),
`GET /v1/phone-numbers/sip-settings` answers `telephony_enabled: false` (the Channels page shows
a notice) and `POST /v1/outbound-calls` answers 503 `telephony_unavailable`. Numbers can still be
imported, labelled and given agents; nothing reaches them.

What `docker-compose.yml` already has: a `sip` service (`livekit/sip`, host network, health on
127.0.0.1:8192) in the `telephony` profile, so `docker compose up -d` never starts it.
`sip.yaml.tmpl` is its configuration; `render-env.sh` renders `sip.yaml` only with
`CW_SIP_ENABLED=true` and writes `LIVEKIT_SIP_HOST` into `worker.env` from `CW_LIVEKIT_SIP_HOST`.

### Turn it on

1. **SIP trunk provider.** Any carrier with BYO SIP trunking: Twilio Elastic SIP Trunking, Telnyx,
   Plivo, Vonage, or an Indian carrier with SIP (Tata Tele, Airtel IQ; Indian DIDs need KYC and
   cannot be used for outbound to Indian mobiles from a foreign trunk). Buy a number, create a
   trunk with **origination** URI `sip:sip.bhawesh.dev` (inbound to us) and **termination**
   (outbound from us) with digest credentials. In Callwright, "Import number" takes the number,
   the termination host (for example `example.pstn.twilio.com`) and those credentials.
2. **DNS.** Cloudflare `sip` A 34.180.13.164, DNS only (SIP and RTP cannot be proxied).
3. **TLS certificate for `sip.bhawesh.dev`** (WhatsApp only connects over TLS). Add a
   `sip.bhawesh.dev { respond 404 }` block to the Caddyfile so Caddy obtains and renews it, then
   copy `fullchain.pem` and `privkey.pem` from the `caddy_data` volume
   (`certificates/acme-v02.api.letsencrypt.org-directory/sip.bhawesh.dev/`) into
   `/opt/callwright/sip-certs/` (repeat after renewal, or mount the volume read-only).
4. **Firewall** (add to `callwright-rtc-public` or a new `callwright-rtc-sip` rule):
   udp 5060 and tcp 5060 (SIP), tcp 5061 (SIP over TLS), udp 51000-51999 (RTP media,
   `CW_SIP_RTP_PORTS`). Restrict 5060 to the carrier's published signalling ranges where it
   publishes them; per-number source ranges can also be set on each number
   (`inbound_allowed_cidrs`).
5. **Render and start** (pin the image to a release from https://github.com/livekit/sip/releases):

   ```bash
   cd /opt/callwright && CW_SIP_ENABLED=true CW_LIVEKIT_SIP_HOST=sip.bhawesh.dev \
     CW_SIP_IMAGE=livekit/sip:<version> ./render-env.sh
   sudo docker compose --profile telephony up -d sip && sudo docker compose up -d worker
   curl -s localhost:8192   # health
   ```

6. **API (Cloud Run).** Set `LIVEKIT_SIP_HOST=sip.bhawesh.dev` on the API service and redeploy.
   With `LIVEKIT_MODE=live` this switches trunks, dispatch rules and WhatsApp to the real APIs.
   Numbers and WhatsApp channels saved while it was off point at in-memory trunk ids: delete
   them and import or connect them again so real trunks are created.
7. **Keep the VM on.** A carrier cannot wake a stopped VM, so inbound calls fail while it is
   off. Touch `/opt/callwright/keep-awake` (or disable `callwright-idle.timer`) once real
   numbers are live.
8. **Verify:** `lk sip inbound list`, `lk sip outbound list`, `lk sip dispatch list` show one
   inbound and one outbound trunk per number and one dispatch rule per number with an inbound
   agent; call the number; place an outbound call from the number's detail panel.

### WhatsApp Business Calling

Needs steps 2 to 7 above (TLS on 5061 is mandatory) and, per number, in Meta: a verified
business, a WhatsApp Business number with the Calling API enabled for the app, a system user
access token with `whatsapp_business_management` and `whatsapp_business_messaging`, and the app
secret. In Callwright, "Connect WhatsApp" takes the phone number ID, the number, the token, a
verify token you choose and the app secret; Callwright enables Calling with SIP delivery to
`sip.bhawesh.dev:5061` and reads the SIP password Meta will use. Then in the Meta app's webhook
settings paste the callback URL shown in the dialog (`https://<api>/v1/whatsapp/webhook`) with
the same verify token and subscribe to the `calls` field. The channel turns `active` when Meta's
verification request arrives.

### Cost

* VM always on: e2-medium in asia-south1 is about USD 25 to 30 a month (today it is usually off),
  plus the static IP.
* Numbers and minutes are billed by the carrier to its account, never by Callwright: for
  example Twilio US local numbers about USD 1.15 a month and Elastic SIP Trunking about
  USD 0.004 to 0.01 a minute; Indian DIDs and minutes vary by carrier.
* WhatsApp: Meta charges per its Calling pricing (user-initiated calls have been free;
  business-initiated calls are billed per minute by country). Check Meta's current price list.
* Callwright bills only connected seconds (from `in_progress`); ringing, busy, no-answer,
  declined and blocked calls cost nothing.
