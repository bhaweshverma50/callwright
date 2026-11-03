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

Disk: the boot disk is 19 GB and each voice worker image is about 2 GB, so every rollout ends
with `sudo docker image prune -af` (it keeps the images of running containers; old tags can be
pulled again from Artifact Registry). It filled up once on 2026-10-27 after 6 voice rollouts.

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
gcloud compute scp deploy/vm/docker-compose.yml deploy/vm/render-env.sh deploy/vm/livekit.yaml.tmpl deploy/vm/egress.yaml.tmpl callwright-rtc:/opt/callwright/ \
  --zone $ZONE --account $ACCOUNT --project $PROJECT
gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
  "cd /opt/callwright && CW_API_IMAGE=$API_IMAGE CW_VOICE_IMAGE=$VOICE_IMAGE ./render-env.sh \
   && sudo docker compose pull worker voice textsim && sudo docker compose up -d worker voice textsim \
   && sudo docker image prune -af"
gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
  "curl -s -o /dev/null -w 'voice %{http_code}\n' localhost:8190; curl -s -o /dev/null -w 'textsim %{http_code}\n' localhost:8193; sudo docker compose -f /opt/callwright/docker-compose.yml logs --tail 30 voice textsim"
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

After a new image is pushed: `cd /opt/callwright && sudo docker compose pull worker && sudo docker compose up -d worker && sudo docker image prune -af`
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

## Call recordings

LiveKit egress (compose service `egress`, profile `recording`) records each call's audio, caller
and agent on separate channels, and uploads an MP4 to the Cloud Storage bucket
`callwright-dev-data`. LiveKit's webhook (rendered into `livekit.yaml`) tells the API when the
file is ready; the call drawer then plays it through a 10 minute signed link. The same bucket
holds uploads (ambience, knowledge documents), which otherwise live in API memory.

Turn on once, in this order:

1. Bucket, service account and keys (into Secret Manager), then access for the API and the VM:
   `deploy/cloudrun/deploy.sh callwright-dev bhaweshverma50@gmail.com storage setup`
2. VM: copy `docker-compose.yml`, `render-env.sh`, `livekit.yaml.tmpl` and `egress.yaml.tmpl`,
   then `CW_RECORDINGS_ENABLED=true ./render-env.sh && sudo docker compose up -d`
   (restarts LiveKit with the webhook; the flag is sticky across later renders). Check:
   `curl -s localhost:8194` and `sudo docker compose logs --tail 20 egress`.
3. API: `deploy.sh ... api` (picks up the bucket settings and `RECORDINGS_ENABLED=true`).

Turn off: `CW_RECORDINGS_ENABLED=false ./render-env.sh && sudo docker compose up -d --remove-orphans`
and `RECORDINGS_ENABLED=false deploy.sh ... api`. Workspace and agent recording settings still
apply on top (an agent set to not record is never recorded). Storage costs about USD 0.02 per
GB a month; a minute of call audio is about 1 MB.

## Telephony: phone numbers and WhatsApp (spec 010)

The API ships phone numbers, outbound calls and WhatsApp channels, but this VM runs no SIP
service yet. Until it does, `LIVEKIT_SIP_HOST` is unset: the API keeps SIP trunks and dispatch
rules in memory (`SIP_MODE=auto`), WhatsApp setup does not call Meta (`WHATSAPP_GRAPH_MODE=auto`),
`GET /v1/phone-numbers/sip-settings` answers `telephony_enabled: false` (the Channels page shows
a notice) and `POST /v1/outbound-calls` answers 503 `telephony_unavailable`. Numbers can still be
imported, labelled and given agents; nothing reaches them.

What `docker-compose.yml` has: a `sip` service (`livekit/sip`, host network, health on
127.0.0.1:8192) in the `telephony` profile and a `lab-pbx` service (Asterisk) in the `lab`
profile. `render-env.sh` turns them on and remembers the choice in `.env` (`LIVEKIT_SIP_HOST`,
`LAB_PBX` and `COMPOSE_PROFILES`), so later renders and a plain `docker compose up -d` keep them:

* `CW_LIVEKIT_SIP_HOST=sip.bhawesh.dev` renders `sip.yaml` from `sip.yaml.tmpl` (plus
  `sip-tls.yaml.tmpl` once `sip-certs/fullchain.pem` exists), adds the `telephony` profile and
  writes `LIVEKIT_SIP_HOST` into `worker.env`. `CW_LIVEKIT_SIP_HOST=` (empty) turns it off.
* `CW_LAB_PBX=true` (needs the SIP host) renders `lab-pbx/pjsip.conf` and adds the `lab` profile.
  `CW_LAB_PBX=false` turns it off.

The API on Cloud Run needs `LIVEKIT_SIP_HOST` as well. `deploy/cloudrun/deploy.sh` keeps whatever
the running service has unless you pass `LIVEKIT_SIP_HOST=...` (or `LIVEKIT_SIP_HOST=` to turn it
off).

### Lab mode: real SIP calls without a phone number

For demos. Asterisk on the VM (`lab-pbx/`) stands in for the carrier: free softphone apps
register to it and call Callwright numbers over real SIP (signalling, RTP media, DTMF), and
Callwright's outbound calls ring them. Nothing reaches the public phone network, so there is no
carrier account, no KYC and no per-minute cost, and the VM keeps its idle shutdown.

```
softphone --SIP 5080--> Asterisk (lab-pbx) --127.0.0.1:5060--> livekit-sip --> LiveKit room + voice agent
```

* Softphones: users `phone1` and `phone2`, caller ids `+919000000001` and `+919000000002`
  (`CW_LAB_CALLER_PREFIX`). One password for both, made on the first render and kept in
  `/opt/callwright/lab-pbx/phone-password`.
* A softphone dialling any number reaches the Callwright number with that E.164.
* Callwright dialling a number rings the softphone named by its last digit:
  `+919000000001` rings `phone1`. Not registered gives 480, a busy phone 486.
* Tested on a laptop with the same images in one network namespace (LiveKit 1.13.3,
  livekit/sip v1.2.0, Asterisk 20.6): softphone to number opens a `call-in-` room with the SIP
  participant; outbound rings a registered phone with the number as caller id and returns
  486/480 as above. Media across the public IP is checked on the VM (step 6 below).

Turn it on:

1. **DNS.** Cloudflare `sip` A 34.180.13.164, DNS only (SIP and RTP cannot be proxied).
2. **Firewall** (only the lab ports; 5060 stays closed until a carrier needs it):

   ```bash
   gcloud compute firewall-rules create callwright-lab-pbx --network default --direction INGRESS \
     --target-tags callwright-rtc --source-ranges 0.0.0.0/0 \
     --allow udp:5080,tcp:5080,udp:52000-52199,udp:51000-51999 \
     --account bhaweshverma50@gmail.com --project callwright-dev
   ```

   udp 51000-51999 is livekit-sip's media range: Asterisk learns livekit-sip's real local
   address from the first RTP packets (`strictrtp`, `rtp_symmetric`), and the open range covers
   the first packets that go to the public address it announces.
3. **Copy and render on the VM** (start it first; touch `keep-awake` while working):

   ```bash
   ACCOUNT=bhaweshverma50@gmail.com; PROJECT=callwright-dev; ZONE=asia-south1-a
   gcloud compute scp --recurse deploy/vm/docker-compose.yml deploy/vm/render-env.sh \
     deploy/vm/sip.yaml.tmpl deploy/vm/sip-tls.yaml.tmpl deploy/vm/lab-pbx \
     callwright-rtc:/opt/callwright/ --zone $ZONE --account $ACCOUNT --project $PROJECT
   gcloud compute ssh callwright-rtc --zone $ZONE --account $ACCOUNT --project $PROJECT -- \
     "cd /opt/callwright && CW_LIVEKIT_SIP_HOST=sip.bhawesh.dev CW_LAB_PBX=true ./render-env.sh \
      && sudo docker compose build lab-pbx && sudo docker compose up -d \
      && curl -s localhost:8192; sudo docker compose exec lab-pbx asterisk -rx 'pjsip show endpoints'"
   ```

   `scp --recurse` of `lab-pbx` copies the templates only; `pjsip.conf` and `phone-password` are
   made on the VM and never leave it.
4. **API.** `LIVEKIT_SIP_HOST=sip.bhawesh.dev deploy/cloudrun/deploy.sh callwright-dev
   bhaweshverma50@gmail.com api`. Numbers imported while SIP was off point at in-memory trunks:
   delete and import them again.
5. **Import a number in Callwright** (Phone numbers, Import): number `+919000000100` (any E.164
   not used by a softphone), termination address `127.0.0.1:5080`, transport UDP, no
   credentials, inbound and outbound agents of your choice. Optionally allow inbound only from
   `127.0.0.1/32`.
6. **Softphone** (Linphone, Zoiper or MicroSIP; on a phone or a laptop): SIP account, username
   `phone1`, domain `sip.bhawesh.dev:5080`, transport UDP, password from
   `sudo cat /opt/callwright/lab-pbx/phone-password`. Codec G.711 (PCMU/PCMA).
   * Inbound: dial `+919000000100`; the inbound agent answers.
   * Outbound: place an outbound call from the number to `+919000000001`; the softphone rings.
   * One-way or no audio means RTP is blocked: check the firewall rule and
     `sudo docker compose logs lab-pbx sip`.

The VM still powers off when idle. A softphone cannot wake it: open the web app first (any API
request starts the VM and shows "Starting the call servers"), then call. Calls in progress keep it
up (the idle check counts LiveKit rooms with participants).

Security: only `phone1` and `phone2` (32-hex password) and livekit-sip on 127.0.0.1 are accepted;
the dialplan has no route anywhere except livekit-sip and the two softphones, so a guessed
password cannot place paid calls. To rotate the password delete `lab-pbx/phone-password` and
render again.

### Real phone numbers (carrier)

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
5. **Render and start** (pin the image to a release from https://github.com/livekit/sip/releases;
   the lab PBX can stay on next to a carrier):

   ```bash
   cd /opt/callwright && CW_LIVEKIT_SIP_HOST=sip.bhawesh.dev \
     CW_SIP_IMAGE=livekit/sip:<version> ./render-env.sh
   sudo docker compose up -d
   curl -s localhost:8192   # health
   ```

6. **API (Cloud Run).** `LIVEKIT_SIP_HOST=sip.bhawesh.dev deploy/cloudrun/deploy.sh ... api`.
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
