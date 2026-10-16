# Realtime VM (GCP, asia-south1)

`callwright-rtc` (e2-medium, static IP 34.180.13.164, project `callwright-dev`) runs Caddy (TLS for
`rtc.bhawesh.dev`), LiveKit server and Redis via `docker-compose.yml`. Secrets live in Secret Manager
(`REDIS_PASSWORD`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`); `render-env.sh` writes `.env` and
`livekit.yaml` on the VM (mode 600). Never commit rendered files.

Firewall: `callwright-rtc-public` allows tcp 80, 443, 7881 and udp 50000-50200 from anywhere;
`callwright-rtc-internal` allows tcp 6379 (Redis) only from internal VPC ranges, used by Cloud Run
through Direct VPC egress.

DNS: Cloudflare record `rtc` A 34.180.13.164, DNS only (not proxied: the proxy breaks WebRTC).

Update: copy files with `gcloud compute scp ... --account bhaweshverma50@gmail.com --project callwright-dev`,
then on the VM `cd /opt/callwright && ./render-env.sh && sudo docker compose up -d`.

The voice worker joins this compose file once vendor keys (Deepgram, OpenAI or Azure OpenAI,
ElevenLabs or Cartesia) are in Secret Manager.

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

After a new image is pushed: `cd /opt/callwright && sudo docker compose pull worker && sudo docker compose up -d worker`.
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
