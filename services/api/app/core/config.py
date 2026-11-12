"""Service settings, read from the environment (and services/api/.env when present).

Secret values may be given in clear text for local development or as an envelope-encrypted
``enc:v1:...`` string produced by ``python -m app.core.secrets encrypt`` (T084); encrypted values
are decrypted at load with ``SECRETS_MASTER_KEY``. Secrets are ``SecretStr`` so they never appear
in reprs, logs or responses.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0123456789abcdef"  # noqa: S105
DEV_WEBHOOK_SECRET = "whsec_dev_fake_stripe_webhook_secret"  # noqa: S105
DEV_MASTER_KEY = "ZGV2LW9ubHktbWFzdGVyLWtleS0zMi1ieXRlcy0hISE="  # 32 bytes, dev only
DEV_SERVICE_TOKEN = "dev-service-token"  # noqa: S105
DEV_LIVEKIT_KEY = "devkey"
DEV_LIVEKIT_SECRET = "secret"  # noqa: S105


_API_DIR = Path(__file__).resolve().parents[2]
# Later files win: the repo-root .env, then services/api/.env.
ENV_FILES = (_API_DIR.parent.parent / ".env", _API_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # dev and test run with offline defaults; staging is a hosted non-production deployment (the
    # demo): dev secrets are refused like prod, but the local IdP, fake Stripe and fake LiveKit
    # are allowed. "production" and "development" are accepted as aliases. No default: a deployment
    # that forgets ENV must fail to start, not come up as dev (dev routes, dev secrets).
    env: Literal["dev", "test", "staging", "prod"]
    version: str = "0.1.0+dev"
    log_level: str = "INFO"
    log_json: bool = False

    # Database: the app role is subject to RLS; the admin role writes the global pricing tables;
    # the owner role runs migrations and maintenance jobs.
    database_url: str = "postgresql+asyncpg://callwright_app:callwright_app@localhost:55432/callwright"
    database_admin_url: str = (
        "postgresql+asyncpg://callwright_admin:callwright_admin@localhost:55432/callwright"
    )
    database_owner_url: str = "postgresql+asyncpg://callwright:callwright@localhost:55432/callwright"
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:56379/0"
    # Fail fast when Redis is away (the realtime VM is stopped): the API then answers 503
    # waking_up instead of hanging on a TCP connect to a powered-off address.
    redis_connect_timeout_s: float = Field(2.0, gt=0, le=30)
    redis_socket_timeout_s: float = Field(5.0, gt=0, le=60)
    # The VM that hosts Redis, LiveKit and the workers (deploy/vm). When all three are set, a
    # Redis outage starts it through the Compute Engine API (app/core/vm_waker.py).
    wake_vm_project: str | None = None
    wake_vm_zone: str | None = None
    wake_vm_name: str | None = None

    # Public URLs
    api_base_url: str = "http://localhost:8100"
    web_base_url: str = "http://localhost:5180"
    # CORS_ORIGINS: comma separated ("https://a.example,https://b.example") or a JSON list.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5180"])
    # Proxies in front of the API that append to X-Forwarded-For (Cloud Run: 1; Cloud Run behind
    # an external HTTPS load balancer: 2). 0 ignores the header and uses the socket peer. Client
    # IPs feed the sign-in throttles and rate limits, so only count proxies you control.
    trusted_proxy_hops: int = Field(0, ge=0, le=5)

    # Identity provider: "local" is the offline dev IdP; "supabase" is production.
    auth_provider: Literal["local", "supabase"] = "local"
    auth_jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    auth_jwks_url: str | None = None
    auth_jwt_audience: str = "authenticated"
    auth_jwt_issuer: str | None = None
    auth_access_token_ttl_s: int = 3600
    # Local IdP: a session (its refresh token) ends this long after sign-in, however active it was.
    # The web signs out after 8 idle hours on its own (useIdleSignOut); this bounds a stolen token.
    auth_session_max_age_s: int = Field(7 * 24 * 3600, gt=0)
    # Hosted demo without email delivery: registration confirms the account at once and returns
    # session tokens. Refused when ENV=prod unless ALLOW_AUTO_VERIFY_IN_PRODUCTION=true.
    auth_auto_verify_email: bool = False
    allow_auto_verify_in_production: bool = False
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    # Signup abuse limits, all off when unset. TURNSTILE_SECRET_KEY makes POST /auth/register
    # require a Cloudflare Turnstile token. SMTP_HOST makes the local IdP email its verification
    # and reset links (the in-memory outbox stays).
    turnstile_secret_key: SecretStr | None = None
    # "Sign in with Google" (also sign-up) on AUTH_PROVIDER=local: on only when both are set. The
    # redirect URI is {WEB_BASE_URL}/auth/google/callback. Not the Drive connector's GOOGLE_OAUTH_*.
    google_signin_client_id: str | None = None
    google_signin_client_secret: SecretStr | None = None
    google_signin_rate_limit_per_hour: int = 60
    # Registration refuses throwaway email domains (app/auth/disposable_domains.txt) plus these.
    block_disposable_email: bool = True
    extra_blocked_email_domains: Annotated[list[str], NoDecode] = []
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None

    # Payments: "fake" serves a local checkout page and signs webhooks with the configured secret.
    stripe_mode: Literal["fake", "live"] = "fake"
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr = SecretStr(DEV_WEBHOOK_SECRET)
    stripe_webhook_tolerance_s: int = 300

    # Business defaults (FR-002, R13)
    trial_credit_usd: Decimal = Decimal("5.00")
    # Cap on trial credit granted per UTC day across all new workspaces; None or 0 is unlimited.
    trial_credit_daily_budget_usd: Decimal | None = None
    default_concurrency: int = 5
    credit_grace_usd: Decimal = Decimal("0.50")

    # Secrets store master key (base64, 32 bytes). Production wraps data keys with a KMS.
    secrets_master_key: SecretStr = SecretStr(DEV_MASTER_KEY)
    # Bearer token for /v1/internal/* (voice worker). The worker reads CALLWRIGHT_SERVICE_TOKEN.
    service_token: SecretStr = Field(
        SecretStr(DEV_SERVICE_TOKEN),
        validation_alias=AliasChoices("service_token", "callwright_service_token"),
    )

    # Voice runtime (003). LIVEKIT_MODE=fake records rooms, dispatches and egress in memory and
    # needs no media server; live talks to LIVEKIT_URL (``livekit-server --dev``: devkey/secret).
    livekit_mode: Literal["live", "fake"] = "live"
    livekit_url: str = "ws://localhost:7880"
    livekit_public_url: str | None = None
    livekit_api_key: SecretStr = SecretStr(DEV_LIVEKIT_KEY)
    livekit_api_secret: SecretStr = SecretStr(DEV_LIVEKIT_SECRET)
    worker_agent_name: str = "callwright-voice"
    # Recordings (research R13): room-composite egress uploads to this bucket with SSE-KMS.
    # RECORDINGS_ENABLED=false admits every call with recording off (``not_recorded``) whatever
    # the workspace and agent settings say: for deployments without a LiveKit egress service.
    recordings_enabled: bool = True
    # A missing or stuck egress service must not hold the recording job: past this the start
    # counts as failed (``recording_status=failed``) and the call goes on unrecorded.
    recordings_egress_timeout_s: float = 20.0
    recordings_bucket: str = "callwright-recordings"
    recordings_s3_endpoint: str | None = None
    recordings_s3_region: str = "us-east-1"
    recordings_s3_access_key: SecretStr | None = None
    recordings_s3_secret_key: SecretStr | None = None
    # Google Cloud Storage: a service account key (JSON). When set, egress uploads with LiveKit's
    # native GCS output instead of the S3 API (GCS's S3 interop rejects newer SDK checksums).
    recordings_gcp_credentials: SecretStr | None = None
    # Outbound customer webhooks (FR-040): plain http only when allowed (development).
    webhooks_allow_http: bool = False
    webhooks_allow_private: bool = False
    # Google connections and Drive knowledge sync (022). All three OAuth values empty turns the
    # feature off: the Connections page says so and its routes return 503 connector_unavailable.
    # The redirect URI is the web app's /settings/connections/callback, registered on the client.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr = SecretStr("")
    google_oauth_redirect_uri: str = ""
    # "fake" serves an in-memory Drive (tests, mock mode, local demos); refused in production.
    connectors_drive_mode: Literal["live", "fake"] = "live"

    # Throttling (R6) and rate limits (R15)
    login_fail_limit: int = 5
    login_fail_ip_limit: int = 20
    login_fail_window_s: int = 900
    quote_rate_limit_per_min: int = 60
    auth_email_rate_limit_per_hour: int = 20

    otel_exporter_otlp_endpoint: str | None = None

    # Development routes. ENABLE_DEV_ROUTES covers /v1/dev/mail and the fake storage previews;
    # ENABLE_FAKE_CHECKOUT covers /v1/dev/fake-checkout (STRIPE_MODE=fake only). Unset means on
    # for ENV=dev and test, off otherwise; fake checkout follows ENABLE_DEV_ROUTES when unset.
    enable_dev_routes: bool | None = None
    enable_fake_checkout: bool | None = None

    # arq polling interval. Metered Redis (Upstash bills per command) is cheaper at 2 to 5 s.
    arq_poll_delay_s: float = Field(0.5, gt=0, le=60)

    # --- 002 agent builder ----------------------------------------------------------------
    # Object storage (ambient audio uploads; later recordings and KB documents). "fake" keeps
    # objects in process memory and serves previews through a signed dev route.
    storage_mode: Literal["fake", "s3"] = "fake"
    s3_endpoint_url: str | None = None  # e.g. http://localhost:59000 for the compose MinIO
    s3_region: str = "us-east-1"
    # Uploads (background ambience, knowledge documents) live in this bucket; the worker gets
    # signed URLs for ambience files from it.
    s3_bucket: str = "callwright"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    # Vendor keys for voice listings (voices/adapters). Without a key the adapter serves its
    # bundled sample list (fake mode).
    elevenlabs_api_key: SecretStr | None = None
    cartesia_api_key: SecretStr | None = None
    # API-side model gateway (llms/client.py). "fake" or a missing provider key selects the
    # deterministic fake adapter.
    prompt_ai_model: str = "azure_openai/gpt-5-mini"
    prompt_ai_timeout_s: float = 60.0
    prompt_ai_rate_limit_per_min: int = 20
    openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "2025-04-01-preview"
    anthropic_api_key: SecretStr | None = None
    # Provider ids the voice worker holds credentials for, comma-separated (``deepgram,openai,
    # elevenlabs``); deploy/cloudrun/deploy.sh computes it from the vendor secrets that exist.
    # Unset: no gating (dev, test and offline runs). Set: live calls and publishing refuse agents
    # that use any other provider (calls/components.py).
    voice_vendor_keys: str | None = None
    # Calls and analytics (006). Model references use the gateway format above; without a key
    # for the provider the module's deterministic planner answers (tests, offline dev).
    analytics_chat_model: str = "openai/gpt-5-mini"
    analytics_chat_rate_limit_per_min: int = 20
    voice_command_model: str = "openai/gpt-5-mini"
    voice_command_rate_limit_per_min: int = 30
    copilot_stt_provider: Literal["deepgram", "fake"] = "deepgram"
    deepgram_api_key: SecretStr | None = None
    recording_url_ttl_s: int = Field(default=600, ge=30, le=600)
    # --- Homepage playground ---------------------------------------------------------------
    # Visitors call published agents of one demo workspace from the home page without an
    # account (app/demo). DEMO_AGENTS maps scenario keys to agent ids, for example
    # "clinic=agt_...,roadside=agt_..."; with DEMO_WORKSPACE_ID unset the playground is off.
    # Calls are charged to the demo workspace, so its balance caps total spend; each visitor
    # IP gets DEMO_CALLS_PER_HOUR calls.
    demo_workspace_id: str | None = None
    demo_agents: str = ""
    demo_calls_per_hour: int = Field(3, ge=1, le=100)
    # --- 010 channels -----------------------------------------------------------------------
    # LIVEKIT_SIP_HOST is the address carriers send calls to (the self-hosted livekit-sip
    # service or a LiveKit Cloud project SIP host). SIP_MODE=auto talks to LiveKit's SIP API
    # only when that host is set and LIVEKIT_MODE=live; otherwise trunks and dispatch rules are
    # kept in memory (tests, offline development, deployments without telephony).
    livekit_sip_host: str | None = None
    sip_mode: Literal["auto", "live", "fake"] = "auto"
    sip_api_timeout_s: float = Field(5.0, gt=0, le=30)
    # WhatsApp Cloud API. WHATSAPP_GRAPH_MODE=auto calls Meta only when telephony is live.
    whatsapp_graph_base_url: str = "https://graph.facebook.com"
    whatsapp_graph_api_version: str = Field("v23.0", pattern=r"^v?\d+\.\d+$")
    whatsapp_graph_mode: Literal["auto", "live", "fake"] = "auto"
    whatsapp_graph_timeout_s: float = Field(10.0, gt=0, le=30)
    # Outbound calls: per-workspace token bucket before admission (research R7).
    outbound_rate_per_second: float = Field(10.0, gt=0)
    outbound_rate_burst: int = Field(20, ge=1)
    # The call_inbound request to an operator's endpoint during the ring phase (R13).
    inbound_webhook_timeout_s: float = Field(3.0, gt=0, le=10)

    # Flow assistant (004). Unset: OpenAI gpt-5-mini when OPENAI_API_KEY is set, else the
    # prompt assistant's model (the fake planner answers without keys).
    flow_assistant_model: str | None = None
    flow_assistant_timeout_s: float = 60.0

    # Quality and evaluations (007). EVAL_JUDGE_MODELS lists the models every judge_model setting
    # may pick (comma separated or a JSON list; the first entry is the default judge).
    # EVAL_JUDGE_MODEL, when set, is the default and is added to the list if missing. Without a
    # key for the provider the deterministic fake judge answers (tests, offline dev).
    eval_judge_models: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["openai/gpt-5-mini"])
    eval_judge_model: str | None = None
    eval_concurrency: int = Field(4, ge=1, le=32)
    eval_timeout_s: float = Field(60.0, gt=0, le=600)
    # Calls shorter than this, or where the caller said fewer characters than this, skip the AI
    # summary and the LLM-judge checks after the call (free checks still run; a manual re-run
    # forces them). Simulations are exempt from the duration rule. 0 turns a rule off.
    analysis_min_duration_s: int = Field(15, ge=0)
    analysis_min_caller_chars: int = Field(40, ge=0)
    # Judge scores at or above the cutoff pass (pinned in each built-in judge's version).
    eval_judge_pass_cutoff: float = Field(0.5, ge=0, le=1)
    calibration_min_sample: int = Field(5, ge=1, le=100)

    # Testing and simulation (008). SIMULATOR_MODEL plays persona callers, writes persona briefs
    # and tool stand-ins; TESTCASE_GENERATOR_MODEL drafts test cases (default: the simulator
    # model). Judges of test cases use the default eval judge. SIM_MAX_CONCURRENCY caps the
    # simulation runs and test cases one workspace executes at once; the rest wait their turn.
    simulator_model: str = "openai/gpt-5-mini"
    testcase_generator_model: str | None = None
    sim_max_concurrency: int = Field(10, ge=1, le=100)
    sim_timeout_s: float = Field(60.0, gt=0, le=600)

    # Issues and auto-fix (009). ISSUES_MODEL names issues and drafts fixes (default: the
    # simulator model). Without a key for its provider the offline fake answers.
    issues_model: str | None = None

    @property
    def google_signin_enabled(self) -> bool:
        return bool(
            self.google_signin_client_id
            and self.google_signin_client_secret
            and self.google_signin_client_secret.get_secret_value()
            and self.auth_provider == "local"
        )

    @property
    def google_signin_redirect_uri(self) -> str:
        return f"{self.web_base_url.rstrip('/')}/auth/google/callback"

    @field_validator("env", mode="before")
    @classmethod
    def _env_alias(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower()
            return {"production": "prod", "development": "dev"}.get(value, value)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
        return value

    @field_validator("eval_judge_models", "extra_blocked_email_domains", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [m.strip() for m in raw.split(",") if m.strip()]
        return value

    @model_validator(mode="after")
    def _check(self) -> Settings:
        from app.core.secrets import decrypt_config_value

        for name in type(self).model_fields:
            value = getattr(self, name)
            if name != "secrets_master_key" and isinstance(value, SecretStr):
                plain = value.get_secret_value()
                if plain.startswith("enc:"):
                    plain = decrypt_config_value(plain, self.secrets_master_key)
                    object.__setattr__(self, name, SecretStr(plain))
        if self.env in ("staging", "prod"):
            insecure = [
                n
                for n, default in (
                    ("auth_jwt_secret", DEV_JWT_SECRET),
                    ("stripe_webhook_secret", DEV_WEBHOOK_SECRET),
                    ("secrets_master_key", DEV_MASTER_KEY),
                    ("service_token", DEV_SERVICE_TOKEN),
                    ("livekit_api_secret", DEV_LIVEKIT_SECRET),
                )
                if getattr(self, n).get_secret_value() == default
                and not (n == "livekit_api_secret" and self.livekit_mode == "fake")
            ]
            if insecure:
                raise ValueError(f"{self.env} settings use dev defaults: {', '.join(insecure)}")
        if self.env == "prod":
            if self.auth_provider == "local" or self.stripe_mode == "fake":
                raise ValueError("production requires AUTH_PROVIDER=supabase and STRIPE_MODE=live")
            if self.connectors_drive_mode == "fake":
                raise ValueError("production refuses CONNECTORS_DRIVE_MODE=fake")
            if self.livekit_mode == "fake" or self.webhooks_allow_http or self.webhooks_allow_private:
                raise ValueError(
                    "production requires LIVEKIT_MODE=live and refuses WEBHOOKS_ALLOW_HTTP/PRIVATE"
                )
        if self.auth_auto_verify_email and self.env == "prod" and not self.allow_auto_verify_in_production:
            raise ValueError(
                "AUTH_AUTO_VERIFY_EMAIL is refused when ENV=prod unless ALLOW_AUTO_VERIFY_IN_PRODUCTION=true"
            )
        if self.auth_provider == "supabase" and not self.supabase_url:
            raise ValueError("AUTH_PROVIDER=supabase requires SUPABASE_URL")
        if self.stripe_mode == "live" and not self.stripe_secret_key:
            raise ValueError("STRIPE_MODE=live requires STRIPE_SECRET_KEY")
        return self

    @property
    def google_configured(self) -> bool:
        """Google connections are available (022): client id, secret and redirect URI all set."""
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret.get_secret_value()
            and self.google_oauth_redirect_uri
        )

    @property
    def fake_drive_routes_enabled(self) -> bool:
        """/v1/dev/fake-drive (022): the dev routes are on and the Drive is the in-memory fake."""
        return self.dev_routes_enabled and self.connectors_drive_mode == "fake"

    @property
    def dev_routes_enabled(self) -> bool:
        """/v1/dev/mail and the fake storage previews."""
        if self.enable_dev_routes is not None:
            return self.enable_dev_routes
        return self.env in ("dev", "test")

    @property
    def fake_checkout_enabled(self) -> bool:
        """/v1/dev/fake-checkout, the stand-in for Stripe's hosted page (STRIPE_MODE=fake only)."""
        if self.stripe_mode != "fake":
            return False
        if self.enable_fake_checkout is not None:
            return self.enable_fake_checkout
        return self.dev_routes_enabled

    @property
    def allow_http_webhooks(self) -> bool:
        """Plain http URLs in agent, tool and flow configuration (webhooks, tool endpoints)."""
        return self.env == "dev"

    @property
    def livekit_client_url(self) -> str:
        """WebSocket URL handed to browsers (defaults to the server URL)."""
        return self.livekit_public_url or self.livekit_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
