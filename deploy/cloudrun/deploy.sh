#!/bin/bash
# Deploy the Callwright API to Cloud Run (see README.md next to this file).
#
#   deploy/cloudrun/deploy.sh PROJECT ACCOUNT [STEP...]
#
# PROJECT and ACCOUNT are required and are passed as --project and --account to EVERY gcloud
# command: the machine's default gcloud account belongs to another organisation and must never be
# used implicitly. Steps (default: check-secrets build migrate api):
#   storage        Cloud Storage bucket for uploads and recordings, its service account and
#                  keys (stored in Secret Manager; run setup after it)
#   setup          enable APIs, Artifact Registry repo, service account, IAM (secrets, VM start,
#                  image pulls by the VM)
#   check-secrets  fail when a required Secret Manager secret is missing
#   build          build and push the image with Cloud Build
#   build-local    build for linux/amd64 with local docker and push it
#   build-voice    build and push the voice worker image with Cloud Build (deploy/vm)
#   build-voice-local  build the voice worker image for linux/amd64 locally and push it
#   migrate        deploy and run the callwright-migrate Cloud Run job (alembic + templates sync)
#   api            deploy the callwright-api service (scale to zero, Direct VPC egress to the VM)
#   worker-hint    print the commands that roll the new images out to the VM (jobs and voice worker)
# Environment overrides: REGION, REPO, TAG, VM_NAME, VM_ZONE, WEB_ORIGIN, LIVEKIT_URL,
# STORAGE_BUCKET, RECORDINGS_ENABLED (default true once the storage keys exist), DRY_RUN=1
# (print the gcloud commands instead of running them).
set -euo pipefail

if [ "$#" -lt 2 ]; then
  sed -n '2,23p' "$0" >&2
  exit 2
fi
PROJECT="$1"
ACCOUNT="$2"
shift 2
STEPS=("$@")
[ "${#STEPS[@]}" -gt 0 ] || STEPS=(check-secrets build migrate api)

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${REGION:-asia-south1}"
REPO="${REPO:-callwright}"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/api:$TAG"
VOICE_IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/voice-worker:$TAG"
SA_NAME="callwright-api"
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
VM_NAME="${VM_NAME:-callwright-rtc}"
VM_ZONE="${VM_ZONE:-asia-south1-a}"
VM_STARTER_ROLE="callwrightVmStarter"
WEB_ORIGIN="${WEB_ORIGIN:-https://callwright-one.vercel.app}"
LIVEKIT_URL="${LIVEKIT_URL:-wss://rtc.bhawesh.dev}"
# Homepage playground (app/demo): published agents in the demo workspace (playground@bhawesh.dev,
# credentials in ~/.config/callwright/demo-account.json). DEMO_WORKSPACE_ID= (empty) turns it off.
DEMO_WORKSPACE_ID="${DEMO_WORKSPACE_ID-ws_01M5YB54ZTTDHJSVXQCB9D21FF}"
DEMO_AGENTS="${DEMO_AGENTS-clinic=agt_01M5YB55MNVTVK1MHD4E70V21K,roadside=agt_01M5YB56PF56Z0RA344HA05DXP,loan=agt_01M5YB57R9YATWAP5HXC8XJ82W}"
DEMO_CALLS_PER_HOUR="${DEMO_CALLS_PER_HOUR:-3}"

# Secrets the API needs (Secret Manager name = env var name).
API_SECRETS=(DATABASE_URL DATABASE_ADMIN_URL REDIS_URL AUTH_JWT_SECRET SECRETS_MASTER_KEY SERVICE_TOKEN
  STRIPE_WEBHOOK_SECRET LIVEKIT_API_KEY LIVEKIT_API_SECRET)
# The migrate role loads the full settings, which refuse dev defaults outside dev and test.
MIGRATE_SECRETS=(DATABASE_OWNER_URL DATABASE_URL DATABASE_ADMIN_URL AUTH_JWT_SECRET SECRETS_MASTER_KEY SERVICE_TOKEN
  STRIPE_WEBHOOK_SECRET)
# Read by the VM (render-env.sh): the worker's secrets plus Redis.
VM_SECRETS=(REDIS_PASSWORD LIVEKIT_API_KEY LIVEKIT_API_SECRET DATABASE_URL DATABASE_ADMIN_URL AUTH_JWT_SECRET
  SECRETS_MASTER_KEY SERVICE_TOKEN STRIPE_WEBHOOK_SECRET)
# Read by the VM's voice worker when they exist (render-env.sh writes voice.env).
VOICE_OPTIONAL_SECRETS=(DEEPGRAM_API_KEY ASSEMBLYAI_API_KEY SARVAM_API_KEY FISHAUDIO_API_KEY SANAS_API_KEY
  AI_COUSTICS_API_KEY)
# Mounted when they exist.
OPTIONAL_SECRETS=(STRIPE_SECRET_KEY OPENAI_API_KEY DEEPGRAM_API_KEY AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY ANTHROPIC_API_KEY
  ELEVENLABS_API_KEY CARTESIA_API_KEY SUPABASE_URL SUPABASE_ANON_KEY
  S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY RECORDINGS_GCP_CREDENTIALS SMTP_PASSWORD TURNSTILE_SECRET_KEY)
# Provider id -> the secrets (joined by +) the voice worker needs to run it; the API gets the ids it
# can run as VOICE_VENDOR_KEYS and refuses live calls for agents on any other provider. Every
# provider of the contract's adapter catalog is listed (a test keeps the two in step); "none"
# (noise cancellation off) is left out; "sanas" needs no secret (its adapter passes audio through).
VENDOR_PROVIDER_SECRETS=(
  deepgram:DEEPGRAM_API_KEY
  assemblyai:ASSEMBLYAI_API_KEY
  sarvam:SARVAM_API_KEY
  openai:OPENAI_API_KEY
  azure_openai:AZURE_OPENAI_ENDPOINT+AZURE_OPENAI_API_KEY
  anthropic:ANTHROPIC_API_KEY
  elevenlabs:ELEVENLABS_API_KEY
  cartesia:CARTESIA_API_KEY
  fishaudio:FISHAUDIO_API_KEY
  sanas:
  ai_coustics:AI_COUSTICS_API_KEY
)
# Object storage (uploads and call recordings): one Cloud Storage bucket, used once its HMAC key
# exists as S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY (deploy/vm/README.md, "Recordings").
STORAGE_BUCKET="${STORAGE_BUCKET:-callwright-dev-data}"

# Every gcloud call goes through here, so --account and --project are never left out.
gc() {
  if [ "${DRY_RUN:-0}" = "1" ]; then
    printf 'gcloud --account=%q --project=%q' "$ACCOUNT" "$PROJECT"
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  gcloud --account="$ACCOUNT" --project="$PROJECT" --quiet "$@"
}

exists() { [ "${DRY_RUN:-0}" = "1" ] || gc "$@" >/dev/null 2>&1; }

secrets_flag() {
  local out="" name
  for name in "$@"; do out+="${out:+,}$name=$name:latest"; done
  printf '%s' "$out"
}

present_secrets() {
  local name
  for name in "$@"; do
    if [ "${DRY_RUN:-0}" != "1" ] && gc secrets describe "$name" >/dev/null 2>&1; then
      printf '%s\n' "$name"
    fi
  done
}

present_optional_secrets() { present_secrets "${OPTIONAL_SECRETS[@]}"; }

# Comma-separated provider ids whose secrets all exist (the VM renders voice.env from the same
# secrets). Azure OpenAI is runnable when OpenAI is: the worker falls back to it without Azure
# (deploy/vm/README.md, "LLM provider"). Empty when nothing is known (dry run).
vendor_voice_keys() {
  local present entry id needs name ok ids=()
  present="$(present_secrets "${OPTIONAL_SECRETS[@]}" "${VOICE_OPTIONAL_SECRETS[@]}")"
  for entry in "${VENDOR_PROVIDER_SECRETS[@]}"; do
    id="${entry%%:*}"
    needs="${entry#*:}"
    ok=1
    for name in ${needs//+/ }; do
      grep -qx "$name" <<<"$present" || ok=0
    done
    [ "$ok" = 1 ] && ids+=("$id")
  done
  case " ${ids[*]-} " in
    *" openai "*) case " ${ids[*]} " in *" azure_openai "*) ;; *) ids+=(azure_openai) ;; esac ;;
  esac
  local IFS=,
  printf '%s' "${ids[*]-}"
}

step_setup() {
  gc services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
    secretmanager.googleapis.com compute.googleapis.com
  exists artifacts repositories describe "$REPO" --location "$REGION" \
    || gc artifacts repositories create "$REPO" --repository-format docker --location "$REGION" \
      --description "Callwright images"
  exists iam service-accounts describe "$SA" \
    || gc iam service-accounts create "$SA_NAME" --display-name "Callwright API (Cloud Run)"
  local name
  for name in "${API_SECRETS[@]}" "${MIGRATE_SECRETS[@]}" "${OPTIONAL_SECRETS[@]}"; do
    if exists secrets describe "$name"; then
      gc secrets add-iam-policy-binding "$name" --member "serviceAccount:$SA" \
        --role roles/secretmanager.secretAccessor --format none
    fi
  done
  # Waking the VM: start (and read) exactly one instance.
  exists iam roles describe "$VM_STARTER_ROLE" \
    || gc iam roles create "$VM_STARTER_ROLE" --title "Callwright VM starter" \
      --description "Start the Callwright realtime VM on demand" \
      --permissions compute.instances.start,compute.instances.get --stage GA
  gc compute instances add-iam-policy-binding "$VM_NAME" --zone "$VM_ZONE" \
    --member "serviceAccount:$SA" --role "projects/$PROJECT/roles/$VM_STARTER_ROLE"
  # The VM pulls the image for its jobs worker and reads the worker's secrets.
  local vm_sa
  if [ "${DRY_RUN:-0}" = "1" ]; then
    vm_sa="VM_SERVICE_ACCOUNT"
  else
    vm_sa="$(gc compute instances describe "$VM_NAME" --zone "$VM_ZONE" \
      --format 'value(serviceAccounts[0].email)')"
  fi
  gc artifacts repositories add-iam-policy-binding "$REPO" --location "$REGION" \
    --member "serviceAccount:$vm_sa" --role roles/artifactregistry.reader --format none
  for name in "${VM_SECRETS[@]}" "${OPTIONAL_SECRETS[@]}" "${VOICE_OPTIONAL_SECRETS[@]}"; do
    if exists secrets describe "$name"; then
      gc secrets add-iam-policy-binding "$name" --member "serviceAccount:$vm_sa" \
        --role roles/secretmanager.secretAccessor --format none
    fi
  done
}

step_check_secrets() {
  local missing=() name
  for name in "${API_SECRETS[@]}" "${MIGRATE_SECRETS[@]}" "${VM_SECRETS[@]}"; do
    exists secrets describe "$name" || missing+=("$name")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "missing Secret Manager secrets: ${missing[*]} (see deploy/cloudrun/README.md)" >&2
    exit 1
  fi
  echo "secrets ok"
}

step_build() {
  gc builds submit "$ROOT" --config "$ROOT/deploy/cloudrun/cloudbuild.yaml" --region "$REGION" \
    --substitutions "_IMAGE=$IMAGE"
}

step_build_local() {
  docker buildx build --platform linux/amd64 -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" --load "$ROOT"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    gc auth print-access-token
  else
    gc auth print-access-token \
      | docker login -u oauth2accesstoken --password-stdin "https://$REGION-docker.pkg.dev"
  fi
  docker push "$IMAGE"
}

step_build_voice() {
  gc builds submit "$ROOT" --config "$ROOT/deploy/vm/cloudbuild-voice.yaml" --region "$REGION" \
    --substitutions "_IMAGE=$VOICE_IMAGE"
}

step_build_voice_local() {
  docker buildx build --platform linux/amd64 -f "$ROOT/services/voice-worker/Dockerfile" \
    -t "$VOICE_IMAGE" --load "$ROOT"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    gc auth print-access-token
  else
    gc auth print-access-token \
      | docker login -u oauth2accesstoken --password-stdin "https://$REGION-docker.pkg.dev"
  fi
  docker push "$VOICE_IMAGE"
}

step_migrate() {
  gc run jobs deploy callwright-migrate --region "$REGION" --image "$IMAGE" \
    --service-account "$SA" --args migrate --tasks 1 --max-retries 0 --task-timeout 900s \
    --cpu 1 --memory 512Mi --set-env-vars LOG_JSON=true,ENV=staging,LIVEKIT_MODE=fake \
    --set-secrets "$(secrets_flag "${MIGRATE_SECRETS[@]}")"
  gc run jobs execute callwright-migrate --region "$REGION" --wait
}

step_api() {
  local url secrets env vendor_keys
  url=""
  if [ "${DRY_RUN:-0}" != "1" ]; then
    url="$(gc run services describe callwright-api --region "$REGION" --format 'value(status.url)' 2>/dev/null || true)"
  fi
  optional="$(present_optional_secrets)"
  # shellcheck disable=SC2086 (one secret name per line, no spaces)
  secrets="$(secrets_flag "${API_SECRETS[@]}" $optional)"
  # "|" separates the variables: CORS_ORIGINS may hold commas and SMTP values hold "@".
  env="^|^ENV=staging|LOG_JSON=true|WEB_BASE_URL=$WEB_ORIGIN|CORS_ORIGINS=$WEB_ORIGIN"
  env+="|TRUSTED_PROXY_HOPS=1|AUTH_PROVIDER=local|AUTH_AUTO_VERIFY_EMAIL=false|TRIAL_CREDIT_USD=1.00|AUTH_EMAIL_RATE_LIMIT_PER_HOUR=3"
  env+="|STRIPE_MODE=fake|ENABLE_FAKE_CHECKOUT=false|ENABLE_DEV_ROUTES=false"
  env+="|LIVEKIT_MODE=live|LIVEKIT_URL=$LIVEKIT_URL|LIVEKIT_PUBLIC_URL=$LIVEKIT_URL"
  env+="|WAKE_VM_PROJECT=$PROJECT|WAKE_VM_ZONE=$VM_ZONE|WAKE_VM_NAME=$VM_NAME|DB_POOL_SIZE=5"
  # Recordings need the bucket (its key in Secret Manager) and the VM's egress service; without
  # the key calls are admitted with recording off and uploads stay in memory.
  if printf '%s\n' "$optional" | grep -qx S3_ACCESS_KEY_ID; then
    env+="|STORAGE_MODE=s3|S3_ENDPOINT_URL=https://storage.googleapis.com|S3_REGION=auto"
    env+="|S3_BUCKET=$STORAGE_BUCKET|RECORDINGS_BUCKET=$STORAGE_BUCKET"
    env+="|RECORDINGS_S3_REGION=auto|AWS_REQUEST_CHECKSUM_CALCULATION=when_required"
    env+="|AWS_RESPONSE_CHECKSUM_VALIDATION=when_required"
    env+="|RECORDINGS_ENABLED=${RECORDINGS_ENABLED:-true}"
  else
    env+="|RECORDINGS_ENABLED=${RECORDINGS_ENABLED:-false}"
  fi
  [ -n "$url" ] && env+="|API_BASE_URL=$url"
  # Which vendors the voice worker can run; unset (nothing found) means the API does not gate.
  vendor_keys="$(vendor_voice_keys)"
  [ -n "$vendor_keys" ] && env+="|VOICE_VENDOR_KEYS=$vendor_keys"
  # 010 telephony: LIVEKIT_SIP_HOST=sip.bhawesh.dev turns SIP on, LIVEKIT_SIP_HOST= (empty) turns
  # it off, unset keeps what the running service has (--set-env-vars would otherwise drop it).
  if [ -z "${LIVEKIT_SIP_HOST+set}" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    LIVEKIT_SIP_HOST="$(gc run services describe callwright-api --region "$REGION" --format json 2>/dev/null \
      | python3 -c 'import json, sys
env = json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env", [])
print(next((e.get("value", "") for e in env if e["name"] == "LIVEKIT_SIP_HOST"), ""))' 2>/dev/null || true)"
  fi
  [ -n "${LIVEKIT_SIP_HOST:-}" ] && env+="|LIVEKIT_SIP_HOST=$LIVEKIT_SIP_HOST"
  # Signup protections (docs/OPERATIONS.md, "Signup abuse protections"): plain settings are passed
  # through from the shell when set; their secrets (SMTP_PASSWORD, TURNSTILE_SECRET_KEY) are optional above.
  # Hosted demo defaults (Brevo SMTP, $5 of trial credit a day); export one as empty to drop it.
  : "${SMTP_HOST=smtp-relay.brevo.com}" "${SMTP_PORT=587}" "${SMTP_USERNAME=b53f68001@smtp-brevo.com}"
  : "${SMTP_FROM=Callwright <mail@bhawesh.dev>}" "${TRIAL_CREDIT_DAILY_BUDGET_USD=5.00}"
  for name in SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_FROM TRIAL_CREDIT_DAILY_BUDGET_USD EXTRA_BLOCKED_EMAIL_DOMAINS; do
    [ -n "${!name:-}" ] && env+="|$name=${!name}"
  done
  if [ -n "$DEMO_WORKSPACE_ID" ]; then
    env+="|DEMO_WORKSPACE_ID=$DEMO_WORKSPACE_ID|DEMO_AGENTS=$DEMO_AGENTS|DEMO_CALLS_PER_HOUR=$DEMO_CALLS_PER_HOUR"
  fi
  gc run deploy callwright-api --region "$REGION" --image "$IMAGE" --service-account "$SA" \
    --allow-unauthenticated --port 8080 --cpu 1 --memory 512Mi --concurrency 40 \
    --min-instances 0 --max-instances 3 --timeout 60s --cpu-boost \
    --network default --subnet default --vpc-egress private-ranges-only \
    --set-env-vars "$env" --set-secrets "$secrets"
  if [ -z "$url" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    url="$(gc run services describe callwright-api --region "$REGION" --format 'value(status.url)')"
    gc run services update callwright-api --region "$REGION" --update-env-vars "API_BASE_URL=$url"
  fi
  echo "API: ${url:-<service url>}  (set Vercel VITE_API_BASE_URL=${url:-<service url>}/v1)"
}

step_worker_hint() {
  local ssh="gcloud compute ssh $VM_NAME --zone $VM_ZONE --account $ACCOUNT --project $PROJECT --"
  local scp="gcloud compute scp --zone $VM_ZONE --account $ACCOUNT --project $PROJECT"
  cat <<EOF
Roll the new images out to the VM (jobs worker: $IMAGE, voice worker: $VOICE_IMAGE).
The VM sleeps when idle: start it first if it is off (any API request wakes it too).
  gcloud compute instances start $VM_NAME --zone $VM_ZONE --account $ACCOUNT --project $PROJECT

1. Copy the compose files (only when deploy/vm changed):
  $scp --recurse deploy/vm/docker-compose.yml deploy/vm/render-env.sh deploy/vm/roll-voice.sh deploy/vm/livekit.yaml.tmpl deploy/vm/egress.yaml.tmpl deploy/vm/sip.yaml.tmpl deploy/vm/sip-tls.yaml.tmpl deploy/vm/lab-pbx $VM_NAME:/opt/callwright/

2. Pin both images and render .env, worker.env and voice.env from Secret Manager:
  $ssh 'cd /opt/callwright && CW_API_IMAGE=$IMAGE CW_VOICE_IMAGE=$VOICE_IMAGE ./render-env.sh'

3. Restart the jobs worker and roll the voice worker (the new one starts before the old one
   drains, so live calls are never cut), then delete the images no container uses (the 19 GB
   disk fills up after a few deploys; old tags stay in Artifact Registry). Restart LiveKit once
   when livekit.yaml.tmpl changed, with no call running:
  $ssh 'cd /opt/callwright && sudo docker compose pull worker && sudo docker compose up -d worker && sudo ./roll-voice.sh && sudo docker image prune -af'
  $ssh 'cd /opt/callwright && sudo docker compose restart livekit'

4. Check them:
  $ssh 'curl -s localhost:8191; echo; curl -s -o /dev/null -w "voice %{http_code}\\n" localhost:8190; curl -s -o /dev/null -w "voice-b %{http_code}\\n" localhost:8195; sudo docker compose -f /opt/callwright/docker-compose.yml logs --tail 30 voice'
EOF
}

# Object storage for uploads and call recordings: the bucket, a service account that may write
# to it, its HMAC key (S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY: API uploads and signed links) and
# a JSON key (RECORDINGS_GCP_CREDENTIALS: LiveKit egress uploads). Keys are created once and go
# straight into Secret Manager, never to the terminal. Run `setup` afterwards so the API and
# the VM may read the new secrets.
step_storage() {
  local sa_name=callwright-storage
  local sa="$sa_name@$PROJECT.iam.gserviceaccount.com"
  exists storage buckets describe "gs://$STORAGE_BUCKET" \
    || gc storage buckets create "gs://$STORAGE_BUCKET" --location "$REGION" \
      --uniform-bucket-level-access --public-access-prevention
  exists iam service-accounts describe "$sa" \
    || gc iam service-accounts create "$sa_name" --display-name "Callwright object storage"
  gc storage buckets add-iam-policy-binding "gs://$STORAGE_BUCKET" \
    --member "serviceAccount:$sa" --role roles/storage.objectAdmin --format none
  [ "${DRY_RUN:-0}" = "1" ] && return 0
  if ! exists secrets describe S3_ACCESS_KEY_ID; then
    gc storage hmac create "$sa" --format json | ACCOUNT="$ACCOUNT" PROJECT="$PROJECT" python3 -c '
import json, os, subprocess, sys
key = json.load(sys.stdin)
for name, value in (("S3_ACCESS_KEY_ID", key["metadata"]["accessId"]), ("S3_SECRET_ACCESS_KEY", key["secret"])):
    subprocess.run(["gcloud", "--account", os.environ["ACCOUNT"], "--project", os.environ["PROJECT"], "--quiet",
        "secrets", "create", name, "--replication-policy", "automatic", "--data-file", "-"],
        input=value.encode(), check=True, stdout=subprocess.DEVNULL)
print("stored the HMAC key as S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY")'
  fi
  if ! exists secrets describe RECORDINGS_GCP_CREDENTIALS; then
    local tmp
    tmp="$(mktemp -d)"
    gc iam service-accounts keys create "$tmp/key.json" --iam-account "$sa" --format none
    # One line (the VM's env files refuse newlines); the private key keeps its escaped "\n".
    python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1])), separators=(",", ":")), end="")' \
      "$tmp/key.json" | gc secrets create RECORDINGS_GCP_CREDENTIALS --replication-policy automatic \
      --data-file - --format none
    rm -rf "$tmp"
    echo "stored the service account key as RECORDINGS_GCP_CREDENTIALS"
  fi
}

for step in "${STEPS[@]}"; do
  echo "== $step"
  case "$step" in
    storage) step_storage ;;
    setup) step_setup ;;
    check-secrets) step_check_secrets ;;
    build) step_build ;;
    build-local) step_build_local ;;
    build-voice) step_build_voice ;;
    build-voice-local) step_build_voice_local ;;
    migrate) step_migrate ;;
    api) step_api ;;
    worker-hint) step_worker_hint ;;
    *) echo "unknown step: $step" >&2; exit 2 ;;
  esac
done
