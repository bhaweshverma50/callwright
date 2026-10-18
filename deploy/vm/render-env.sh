#!/bin/bash
# Run on the VM. Pulls secrets from Secret Manager (VM service account needs
# roles/secretmanager.secretAccessor) and renders .env, worker.env, voice.env and livekit.yaml next
# to this script. worker.env feeds the arq jobs worker (the API image in ROLE=worker) and the idle
# check; voice.env feeds the voice worker. .env pins API_IMAGE and VOICE_IMAGE for compose.
#
# Non-secret settings can be overridden when running it, for example
#   CW_ENV=staging CW_WEB_BASE_URL=https://callwright-one.vercel.app \
#   CW_API_BASE_URL=https://callwright-api-xxxx.a.run.app CW_VOICE_IMAGE=<image> ./render-env.sh
set -euo pipefail
cd "$(dirname "$0")"
# The Cloud Run API (deploy/cloudrun). The voice worker calls $CW_API_BASE_URL/v1/internal.
DEFAULT_API_BASE_URL="https://callwright-api-c3nx326hwq-el.a.run.app"
CW_API_BASE_URL="${CW_API_BASE_URL:-$DEFAULT_API_BASE_URL}"
CW_API_BASE_URL="${CW_API_BASE_URL%/}"
secret() { gcloud secrets versions access latest --secret="$1"; }
# Optional secrets: empty when the secret does not exist yet.
secret_opt() { gcloud secrets versions access latest --secret="$1" 2>/dev/null || true; }
umask 077
REDIS_PASSWORD="$(secret REDIS_PASSWORD)"
LIVEKIT_API_KEY="$(secret LIVEKIT_API_KEY)"
LIVEKIT_API_SECRET="$(secret LIVEKIT_API_SECRET)"
# Keep the pinned worker images across re-renders (CW_API_IMAGE and CW_VOICE_IMAGE override them).
PREV_API_IMAGE="$(sed -n 's/^API_IMAGE=//p' .env 2>/dev/null || true)"
API_IMAGE="${CW_API_IMAGE:-${PREV_API_IMAGE:-asia-south1-docker.pkg.dev/callwright-dev/callwright/api:latest}}"
PREV_VOICE_IMAGE="$(sed -n 's/^VOICE_IMAGE=//p' .env 2>/dev/null || true)"
VOICE_IMAGE="${CW_VOICE_IMAGE:-${PREV_VOICE_IMAGE:-asia-south1-docker.pkg.dev/callwright-dev/callwright/voice-worker:latest}}"
printf 'REDIS_PASSWORD=%s\nAPI_IMAGE=%s\nVOICE_IMAGE=%s\n' "$REDIS_PASSWORD" "$API_IMAGE" "$VOICE_IMAGE" > .env
export REDIS_PASSWORD LIVEKIT_API_KEY LIVEKIT_API_SECRET
envsubst < livekit.yaml.tmpl > livekit.yaml

# worker.env: compose env_file with single-quoted literal values (no interpolation).
line() {
  local key="$1" value="$2"
  [ -z "$value" ] && return 0
  case "$value" in
    *"'"* | *$'\n'*) echo "refusing $key: value contains a quote or newline" >&2; exit 1 ;;
  esac
  printf "%s='%s'\n" "$key" "$value"
}
# Required secrets, fetched first so a missing one stops the script (set -e).
DATABASE_URL="$(secret DATABASE_URL)"
DATABASE_ADMIN_URL="$(secret DATABASE_ADMIN_URL)"
AUTH_JWT_SECRET="$(secret AUTH_JWT_SECRET)"
SECRETS_MASTER_KEY="$(secret SECRETS_MASTER_KEY)"
SERVICE_TOKEN="$(secret SERVICE_TOKEN)"
STRIPE_WEBHOOK_SECRET="$(secret STRIPE_WEBHOOK_SECRET)"
REDIS_URL_ENCODED_PASSWORD="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$REDIS_PASSWORD")"
{
  line ENV "${CW_ENV:-staging}"
  line LOG_JSON true
  line WEB_BASE_URL "${CW_WEB_BASE_URL:-https://callwright-one.vercel.app}"
  line API_BASE_URL "$CW_API_BASE_URL"
  line AUTH_PROVIDER "${CW_AUTH_PROVIDER:-local}"
  line STRIPE_MODE "${CW_STRIPE_MODE:-fake}"
  line ARQ_POLL_DELAY_S "${CW_ARQ_POLL_DELAY_S:-1}"
  line RECORDINGS_ENABLED "${CW_RECORDINGS_ENABLED:-false}"
  line REDIS_URL "redis://:${REDIS_URL_ENCODED_PASSWORD}@127.0.0.1:6379/0"
  line LIVEKIT_MODE live
  line LIVEKIT_URL "ws://127.0.0.1:7880"
  line LIVEKIT_PUBLIC_URL "${CW_LIVEKIT_PUBLIC_URL:-wss://rtc.bhawesh.dev}"
  line LIVEKIT_API_KEY "$LIVEKIT_API_KEY"
  line LIVEKIT_API_SECRET "$LIVEKIT_API_SECRET"
  line DATABASE_URL "$DATABASE_URL"
  line DATABASE_ADMIN_URL "$DATABASE_ADMIN_URL"
  line AUTH_JWT_SECRET "$AUTH_JWT_SECRET"
  line SECRETS_MASTER_KEY "$SECRETS_MASTER_KEY"
  line SERVICE_TOKEN "$SERVICE_TOKEN"
  line STRIPE_WEBHOOK_SECRET "$STRIPE_WEBHOOK_SECRET"
  for name in STRIPE_SECRET_KEY OPENAI_API_KEY AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY \
    ANTHROPIC_API_KEY ELEVENLABS_API_KEY CARTESIA_API_KEY SUPABASE_URL SUPABASE_ANON_KEY \
    SUPABASE_SERVICE_KEY; do
    line "$name" "$(secret_opt "$name")"
  done
} > worker.env.tmp
mv worker.env.tmp worker.env

# voice.env: the voice worker (services/voice-worker). It holds no database or storage
# credentials, only LiveKit, the internal API and the vendor keys that exist in Secret Manager.
# The ElevenLabs plugin reads ELEVEN_API_KEY. Without Azure OpenAI secrets, agents on the default
# azure_openai provider run on OpenAI with OPENAI_API_KEY (worker/settings.py).
{
  line WORKER_ROLE live
  line WORKER_AGENT_NAME "${CW_WORKER_AGENT_NAME:-callwright-voice}"
  line WORKER_HEALTH_PORT 8190
  line WORKER_NUM_IDLE_PROCESSES "${CW_VOICE_IDLE_PROCESSES:-2}"
  line WORKER_LOAD_THRESHOLD "${CW_VOICE_LOAD_THRESHOLD:-0.9}"
  line LIVEKIT_URL "ws://127.0.0.1:7880"
  line LIVEKIT_API_KEY "$LIVEKIT_API_KEY"
  line LIVEKIT_API_SECRET "$LIVEKIT_API_SECRET"
  line CALLWRIGHT_INTERNAL_API_URL "$CW_API_BASE_URL/v1/internal"
  line CALLWRIGHT_SERVICE_TOKEN "$SERVICE_TOKEN"
  line CALLWRIGHT_OTEL_EXPORTER none
  line DEEPGRAM_API_KEY "$(secret_opt DEEPGRAM_API_KEY)"
  line OPENAI_API_KEY "$(secret_opt OPENAI_API_KEY)"
  line AZURE_OPENAI_ENDPOINT "$(secret_opt AZURE_OPENAI_ENDPOINT)"
  line AZURE_OPENAI_API_KEY "$(secret_opt AZURE_OPENAI_API_KEY)"
  line ELEVEN_API_KEY "$(secret_opt ELEVENLABS_API_KEY)"
  for name in CARTESIA_API_KEY ASSEMBLYAI_API_KEY SARVAM_API_KEY FISHAUDIO_API_KEY \
    SANAS_API_KEY AI_COUSTICS_API_KEY; do
    line "$name" "$(secret_opt "$name")"
  done
} > voice.env.tmp
mv voice.env.tmp voice.env
echo "rendered .env, worker.env, voice.env and livekit.yaml"
