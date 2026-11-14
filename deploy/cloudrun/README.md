# Callwright API on Cloud Run

Hosted demo topology:

| Piece | Where | Notes |
|---|---|---|
| API (`callwright-api`) | Cloud Run service, asia-south1, scale to zero | image `services/api/Dockerfile`, `ROLE=api` |
| Migrations (`callwright-migrate`) | Cloud Run job | same image, `ROLE=migrate`: `alembic upgrade head`, then the templates sync |
| Redis, LiveKit, jobs worker, voice worker | VM `callwright-rtc` (asia-south1-a, internal 10.160.0.2) | `deploy/vm`; powers off after 15 idle minutes, the API wakes it |
| Postgres + pgvector | Cloud SQL `callwright-pg` (PG 17, db-f1-micro, private IP 10.54.32.3 on `default`) | app, admin and owner roles direct on 5432 with `sslmode=require`; reached over Direct VPC egress (API and migrate job) and from the VM |
| Web | Vercel, https://callwright-one.vercel.app | `VITE_API_BASE_URL` points at the API |

One image serves every role. The role comes from the first container argument or `ROLE`
(`api` by default); `worker` runs arq plus a health listener on `PORT` (used on the VM, port 8191);
`migrate` exits when done. Any other argument runs as a command, for example
`docker run --rm IMAGE python -m app.dev.make_admin ops@example.com`.

## Ground rule: explicit account and project

The machine's default gcloud account belongs to another organisation. Every command below passes
`--account` and `--project`; `deploy.sh` takes both as required arguments and adds them to every
gcloud call. Set these in your shell first:

```bash
ACCOUNT=bhaweshverma50@gmail.com
PROJECT=callwright-dev
REGION=asia-south1
```

## 1. Database (once)

Hosted on Cloud SQL since 2026-11-14 (moved off Supabase; final Supabase dumps are in
`gs://callwright-dev-db-backups/supabase-final-2026-11-14/`). Cloud SQL's `postgres` lacks
BYPASSRLS by default: run `ALTER ROLE postgres BYPASSRLS` once, then the bootstrap below over the
instance's IP (temporarily add a public IP with your address authorised, then `--no-assign-ip`).
The `postgres` password is in the `CLOUDSQL_POSTGRES_PASSWORD` secret. The Supabase steps below
still apply to a Supabase database.

### Supabase

1. Do not enable `vector` from the dashboard (it would land in schema `extensions`): the
   bootstrap script installs `citext` and `vector` in schema `public`, where the RLS lookup
   functions (`search_path = public`) need them.
2. Run the bootstrap over a session connection (direct `db.<ref>.supabase.co:5432`, which is
   IPv6 only, or the IPv4 session pooler `aws-0-<region>.pooler.supabase.com:5432` with user
   `postgres.<ref>`), as `postgres`:

   ```bash
   psql "postgresql://postgres.<ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
     -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" -v admin_password="$ADMIN_DB_PASSWORD" \
     -f scripts/bootstrap_managed_db.sql
   ```

   It checks that `postgres` has CREATEROLE and BYPASSRLS (Supabase's does; the migrations'
   security definer lookups rely on the table owner bypassing RLS), and creates or updates:

   | Role | Login | RLS | Used by |
   |---|---|---|---|
   | `postgres` (exists) | yes | bypasses | migrations: owns every table and function (`DATABASE_OWNER_URL`) |
   | `callwright_app` | yes, `app_password` | enforced | every tenant query (`DATABASE_URL`) |
   | `callwright_admin` | yes, `admin_password` | enforced | pricing catalog writes, maintenance reads (`DATABASE_ADMIN_URL`) |

   Re-running it rotates the two passwords (update the secrets afterwards). If it stops at the
   extension step because `vector` was enabled from the dashboard in schema `extensions`, disable
   it in the dashboard and run the script again (no table uses it yet).
3. URLs (any `postgresql://` URL is accepted; the driver is chosen by the app):

   | Secret | URL | Why |
   |---|---|---|
   | `DATABASE_URL` | `postgresql://callwright_app.<ref>:<app-pw>@aws-0-<region>.pooler.supabase.com:6543/postgres` | transaction pooler: port 6543 switches off asyncpg prepared statement caches |
   | `DATABASE_ADMIN_URL` | same with `callwright_admin.<ref>` | |
   | `DATABASE_OWNER_URL` | `postgresql://postgres.<ref>:<db-pw>@aws-0-<region>.pooler.supabase.com:5432/postgres` | session connection for DDL; the migrate job refuses port 6543 |

   Add `?sslmode=require` if you want TLS enforced (it is translated per driver). A pooler on
   another port can be marked with `?pgbouncer=true`. Check the custom roles log in through the
   pooler (`psql "<DATABASE_URL>" -c 'select current_user'`) before deploying.

   Current values (Cloud SQL, no pooler): all three secrets use
   `postgresql://<role>:<pw>@10.54.32.3:5432/postgres?sslmode=require` with role
   `callwright_app`, `callwright_admin` or `postgres`.

## 2. Secrets (Secret Manager, once per value)

Create each with the value on stdin (no shell history, no files):

```bash
printf %s "$VALUE" | gcloud secrets create NAME --data-file=- --replication-policy=automatic \
  --account "$ACCOUNT" --project "$PROJECT"
# new version later:
printf %s "$VALUE" | gcloud secrets versions add NAME --data-file=- --account "$ACCOUNT" --project "$PROJECT"
```

| Secret | Used by | Value |
|---|---|---|
| `DATABASE_URL` | API, migrate job, VM worker | pooled app role URL (above) |
| `DATABASE_ADMIN_URL` | API, migrate job, VM worker | pooled admin role URL |
| `DATABASE_OWNER_URL` | migrate job | session `postgres` URL |
| `REDIS_URL` | API | `redis://:<REDIS_PASSWORD url-encoded>@10.160.0.2:6379/0` (the VM's Redis over Direct VPC egress) |
| `REDIS_PASSWORD` | VM (exists) | Redis password; keep `REDIS_URL` in step |
| `AUTH_JWT_SECRET` | API, VM worker | 48+ random characters (`openssl rand -base64 48`) |
| `SECRETS_MASTER_KEY` | API, VM worker | 32 random bytes, base64 (`openssl rand -base64 32`) |
| `SERVICE_TOKEN` | API, VM worker, VM voice worker | random token for `/v1/internal/*` |
| `STRIPE_WEBHOOK_SECRET` | API, VM worker | any random value in fake Stripe mode (signs the fake checkout events) |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | API, VM (exist) | the self-hosted LiveKit keys |
| optional, voice worker only: `DEEPGRAM_API_KEY`, `ASSEMBLYAI_API_KEY`, `SARVAM_API_KEY`, `FISHAUDIO_API_KEY`, `SANAS_API_KEY`, `AI_COUSTICS_API_KEY` | VM voice worker | written to `voice.env` when the secret exists (`deploy/vm/README.md`) |
| optional: `STRIPE_SECRET_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `CARTESIA_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | API, VM worker | mounted only when the secret exists; without them the adapters run in fake mode |

`ENV=staging` refuses the development defaults of `AUTH_JWT_SECRET`, `SECRETS_MASTER_KEY`,
`SERVICE_TOKEN`, `STRIPE_WEBHOOK_SECRET` and `LIVEKIT_API_SECRET`, so a missing secret stops the
service at startup instead of running with a known key.

## 3. Deploy

```bash
deploy/cloudrun/deploy.sh "$PROJECT" "$ACCOUNT" setup          # once: APIs, registry, IAM
deploy/cloudrun/deploy.sh "$PROJECT" "$ACCOUNT"                # check-secrets build migrate api
deploy/cloudrun/deploy.sh "$PROJECT" "$ACCOUNT" build-voice    # voice worker image (deploy/vm/cloudbuild-voice.yaml)
deploy/cloudrun/deploy.sh "$PROJECT" "$ACCOUNT" worker-hint    # how to roll both images out to the VM workers
DRY_RUN=1 deploy/cloudrun/deploy.sh "$PROJECT" "$ACCOUNT" setup build migrate api   # print only
```

`build` uses Cloud Build (`cloudbuild.yaml`, upload filtered by `.gcloudignore`); `build-local`
builds `linux/amd64` with local docker and pushes with a token from
`gcloud auth print-access-token --account ... --project ...` (no credential helper, so the
default account is never used). The image tag is the git short sha (`TAG=` overrides).

The commands `deploy.sh` runs, for reference:

```bash
IMAGE=$REGION-docker.pkg.dev/$PROJECT/callwright/api:$(git rev-parse --short HEAD)
SA=callwright-api@$PROJECT.iam.gserviceaccount.com

# setup
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com compute.googleapis.com --account "$ACCOUNT" --project "$PROJECT"
gcloud artifacts repositories create callwright --repository-format docker --location "$REGION" \
  --account "$ACCOUNT" --project "$PROJECT"
gcloud iam service-accounts create callwright-api --display-name "Callwright API (Cloud Run)" \
  --account "$ACCOUNT" --project "$PROJECT"
gcloud secrets add-iam-policy-binding NAME --member "serviceAccount:$SA" \
  --role roles/secretmanager.secretAccessor --account "$ACCOUNT" --project "$PROJECT"   # per secret
gcloud iam roles create callwrightVmStarter --title "Callwright VM starter" \
  --permissions compute.instances.start,compute.instances.get --stage GA \
  --account "$ACCOUNT" --project "$PROJECT"
gcloud compute instances add-iam-policy-binding callwright-rtc --zone asia-south1-a \
  --member "serviceAccount:$SA" --role "projects/$PROJECT/roles/callwrightVmStarter" \
  --account "$ACCOUNT" --project "$PROJECT"

# build
gcloud builds submit . --config deploy/cloudrun/cloudbuild.yaml --region "$REGION" \
  --substitutions "_IMAGE=$IMAGE" --account "$ACCOUNT" --project "$PROJECT"

# migrate (Cloud Run job, then run it)
gcloud run jobs deploy callwright-migrate --region "$REGION" --image "$IMAGE" --service-account "$SA" \
  --args migrate --tasks 1 --max-retries 0 --task-timeout 900s --set-env-vars LOG_JSON=true \
  --set-secrets DATABASE_OWNER_URL=DATABASE_OWNER_URL:latest,DATABASE_URL=DATABASE_URL:latest,DATABASE_ADMIN_URL=DATABASE_ADMIN_URL:latest \
  --account "$ACCOUNT" --project "$PROJECT"
gcloud run jobs execute callwright-migrate --region "$REGION" --wait --account "$ACCOUNT" --project "$PROJECT"

# api (see the env table below for the full --set-env-vars list)
gcloud run deploy callwright-api --region "$REGION" --image "$IMAGE" --service-account "$SA" \
  --allow-unauthenticated --port 8080 --cpu 1 --memory 512Mi --concurrency 40 \
  --min-instances 0 --max-instances 3 --timeout 60s --cpu-boost \
  --network default --subnet default --vpc-egress private-ranges-only \
  --set-env-vars "^@^ENV=staging@CORS_ORIGINS=https://callwright-one.vercel.app@..." \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,..." --account "$ACCOUNT" --project "$PROJECT"
```

The API reaches Redis on the VM's internal address through Direct VPC egress
(`--network default --subnet default --vpc-egress private-ranges-only`); the VM firewall rule
`callwright-rtc-internal` already allows tcp 6379 from internal ranges, which include the
subnet Cloud Run egresses from. Public traffic (Supabase, LiveKit over `wss://rtc.bhawesh.dev`)
keeps the default internet path.

## 4. API environment

| Variable | Value | Secret |
|---|---|---|
| `ENV` | `staging` (hosted, not production: refuses dev secrets, allows the demo adapters below) | no |
| `LOG_JSON` | `true` | no |
| `API_BASE_URL` | the service URL (set by `deploy.sh` after the first deploy) | no |
| `WEB_BASE_URL` | `https://callwright-one.vercel.app` | no |
| `CORS_ORIGINS` | `https://callwright-one.vercel.app` (comma separated list) | no |
| `TRUSTED_PROXY_HOPS` | `1` (client IP for throttles from the right of X-Forwarded-For) | no |
| `AUTH_PROVIDER` | `local` | no |
| `AUTH_AUTO_VERIFY_EMAIL` | `true` (no mail delivery: register signs straight in; refused with `ENV=prod` unless `ALLOW_AUTO_VERIFY_IN_PRODUCTION=true`) | no |
| `STRIPE_MODE` | `fake` | no |
| `ENABLE_FAKE_CHECKOUT` | `true` (only `/v1/dev/fake-checkout`) | no |
| `ENABLE_DEV_ROUTES` | `false` (`/v1/dev/mail` and storage previews stay off) | no |
| `LIVEKIT_MODE` | `live` | no |
| `LIVEKIT_URL`, `LIVEKIT_PUBLIC_URL` | `wss://rtc.bhawesh.dev` | no |
| `WAKE_VM_PROJECT`, `WAKE_VM_ZONE`, `WAKE_VM_NAME` | `callwright-dev`, `asia-south1-a`, `callwright-rtc` | no |
| `DB_POOL_SIZE` | `5` | no |
| `RECORDINGS_ENABLED` | `true` once the storage keys exist (`deploy.sh ... storage`), otherwise `false` (calls admitted with recording off, `not_recorded`). With `true` and no egress service on the VM, the recording start fails within `RECORDINGS_EGRESS_TIMEOUT_S` (20 s), the call goes on, and it reads `recording_status=failed` with a `recording_unavailable` processing warning | no |
| `STORAGE_MODE` and `S3_*`, `*_BUCKET` | set by `deploy.sh` when the `S3_ACCESS_KEY_ID` secret exists: Cloud Storage bucket `STORAGE_BUCKET` (default `callwright-dev-data`) over its S3 API for uploads, recordings and signed links | no |
| `REDIS_CONNECT_TIMEOUT_S`, `REDIS_SOCKET_TIMEOUT_S` | defaults `2`, `5` (a stopped VM fails fast) | no |
| `DATABASE_URL`, `DATABASE_ADMIN_URL`, `REDIS_URL`, `AUTH_JWT_SECRET`, `SECRETS_MASTER_KEY`, `SERVICE_TOKEN`, `STRIPE_WEBHOOK_SECRET`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (+ optional vendor keys) | see section 2 | yes |
| `PORT` | set by Cloud Run | no |

## 5. Waking the VM (IAM)

When Redis does not answer (the VM powered itself off), the API replies 503 problem+json
`code: waking_up` with `Retry-After: 45`, and calls
`POST https://compute.googleapis.com/compute/v1/projects/callwright-dev/zones/asia-south1-a/instances/callwright-rtc/start`
with the service account token from the metadata server, at most once a minute per instance.
The web app shows "Starting servers" and retries until the API answers (about a minute).

The Cloud Run service account needs permission to start that one VM. `deploy.sh setup` creates the
custom role `callwrightVmStarter` (`compute.instances.start`, `compute.instances.get`) and binds
it on the instance only. The alternative is `roles/compute.instanceAdmin.v1`, also bound on the
instance (`gcloud compute instances add-iam-policy-binding callwright-rtc ...`), never on the
project. If the start call is refused with a message about `iam.serviceAccounts.actAs`, also
grant `roles/iam.serviceAccountUser` on the VM's service account to `callwright-api@...`.

The VM's own service account needs `roles/artifactregistry.reader` on the `callwright`
repository (worker image) and `roles/secretmanager.secretAccessor` on the worker's secrets;
`deploy.sh setup` grants both.

## 6. Web (Vercel)

The web reads its API base from `VITE_API_BASE_URL` at build time; nothing is hard-coded. In
the Vercel project settings (Production environment) set:

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://<callwright-api service url>/v1` |
| `VITE_API_MOCKS` | `false` |

`apps/web/vercel.json` builds with `pnpm build:mock`, whose `.env.mock` turns the in-browser mock
API on; variables set in the Vercel environment take precedence over `.env.mock`, so the two
above switch the hosted build to the real API without a code change. (Changing the build command
to `pnpm build` is the cleaner long-term setting.) Redeploy the web after changing them.

## 7. Checks after a deploy

```bash
URL=$(gcloud run services describe callwright-api --region "$REGION" --format 'value(status.url)' \
  --account "$ACCOUNT" --project "$PROJECT")
curl -s "$URL/v1/health"                                   # {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' "$URL/v1/pricing/catalog"   # 200 (no Redis needed)
curl -s -o /dev/null -w '%{http_code}\n' "$URL/v1/dev/mail"          # 404
gcloud run services logs read callwright-api --region "$REGION" --limit 50 --account "$ACCOUNT" --project "$PROJECT"
```

Known limits of the demo setup: without the storage keys (`deploy.sh ... storage`), uploads
stay in instance memory (lost when the API scales to zero) and calls are not recorded. With auto-verify on, registering a taken email answers 202 while a new one answers 200,
which reveals that the email exists.
