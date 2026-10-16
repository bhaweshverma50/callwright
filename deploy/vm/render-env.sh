#!/bin/bash
# Run on the VM. Pulls secrets from Secret Manager (VM service account needs
# roles/secretmanager.secretAccessor) and renders .env and livekit.yaml next to this script.
set -euo pipefail
cd "$(dirname "$0")"
secret() { gcloud secrets versions access latest --secret="$1"; }
umask 077
REDIS_PASSWORD="$(secret REDIS_PASSWORD)"
LIVEKIT_API_KEY="$(secret LIVEKIT_API_KEY)"
LIVEKIT_API_SECRET="$(secret LIVEKIT_API_SECRET)"
printf 'REDIS_PASSWORD=%s\n' "$REDIS_PASSWORD" > .env
export REDIS_PASSWORD LIVEKIT_API_KEY LIVEKIT_API_SECRET
envsubst < livekit.yaml.tmpl > livekit.yaml
echo "rendered .env and livekit.yaml"
