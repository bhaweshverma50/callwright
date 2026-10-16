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
