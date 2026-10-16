#!/bin/bash
# Run on the VM. Pulls secrets from Secret Manager (VM service account needs
# roles/secretmanager.secretAccessor) and renders .env, worker.env and livekit.yaml next to this
# script. worker.env feeds the arq jobs worker (the API image in ROLE=worker) and the idle check.
#
# Non-secret worker settings can be overridden when running it, for example
#   CW_ENV=staging CW_WEB_BASE_URL=https://callwright-one.vercel.app \
#   CW_API_BASE_URL=https://callwright-api-xxxx.a.run.app ./render-env.sh
set -euo pipefail
cd "$(dirname "$0")"
secret() { gcloud secrets versions access latest --secret="$1"; }
# Optional secrets: empty when the secret does not exist yet.
secret_opt() { gcloud secrets versions access latest --secret="$1" 2>/dev/null || true; }
umask 077
REDIS_PASSWORD="$(secret REDIS_PASSWORD)"
LIVEKIT_API_KEY="$(secret LIVEKIT_API_KEY)"
LIVEKIT_API_SECRET="$(secret LIVEKIT_API_SECRET)"
# Keep the pinned worker image across re-renders (CW_API_IMAGE overrides it).
PREV_API_IMAGE="$(sed -n 's/^API_IMAGE=//p' .env 2>/dev/null || true)"
API_IMAGE="${CW_API_IMAGE:-${PREV_API_IMAGE:-asia-south1-docker.pkg.dev/callwright-dev/callwright/api:latest}}"
printf 'REDIS_PASSWORD=%s\nAPI_IMAGE=%s\n' "$REDIS_PASSWORD" "$API_IMAGE" > .env
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
  line API_BASE_URL "${CW_API_BASE_URL:-}"
  line AUTH_PROVIDER "${CW_AUTH_PROVIDER:-local}"
  line STRIPE_MODE "${CW_STRIPE_MODE:-fake}"
  line ARQ_POLL_DELAY_S "${CW_ARQ_POLL_DELAY_S:-1}"
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
echo "rendered .env, worker.env and livekit.yaml"
