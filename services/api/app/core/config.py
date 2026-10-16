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
    # are allowed. "production" and "development" are accepted as aliases.
    env: Literal["dev", "test", "staging", "prod"] = "dev"
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
    # Hosted demo without email delivery: registration confirms the account at once and returns
    # session tokens. Refused when ENV=prod unless ALLOW_AUTO_VERIFY_IN_PRODUCTION=true.
    auth_auto_verify_email: bool = False
    allow_auto_verify_in_production: bool = False
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_key: SecretStr | None = None

    # Payments: "fake" serves a local checkout page and signs webhooks with the configured secret.
    stripe_mode: Literal["fake", "live"] = "fake"
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr = SecretStr(DEV_WEBHOOK_SECRET)
    stripe_webhook_tolerance_s: int = 300

    # Business defaults (FR-002, R13)
    trial_credit_usd: Decimal = Decimal("5.00")
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
    # The worker's adapter catalog (003 research R8), read at admission to refuse unsupported
    # vendors before a room exists.
    adapter_catalog_path: Path = _API_DIR.parent / "voice-worker" / "worker" / "adapters" / "catalog.json"
    # Recordings (research R13): room-composite egress uploads to this bucket with SSE-KMS.
    recordings_bucket: str = "callwright-recordings"
    recordings_s3_endpoint: str | None = None
    recordings_s3_region: str = "us-east-1"
    recordings_s3_access_key: SecretStr | None = None
    recordings_s3_secret_key: SecretStr | None = None
    recordings_kms_key_id: str | None = None
    # Uploaded media (background ambience files, 002) served to the worker by signed URL.
    media_bucket: str = "callwright-media"
    # Outbound customer webhooks (FR-040): plain http only when allowed (development).
    webhooks_allow_http: bool = False
    webhooks_allow_private: bool = False

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

    @model_validator(mode="after")
    def _check(self) -> Settings:
        from app.core.secrets import decrypt_config_value

        for name in (
            "auth_jwt_secret",
            "supabase_anon_key",
            "supabase_service_key",
            "stripe_secret_key",
            "stripe_webhook_secret",
            "service_token",
            "livekit_api_secret",
            "recordings_s3_secret_key",
            "s3_access_key_id",
            "s3_secret_access_key",
            "elevenlabs_api_key",
            "cartesia_api_key",
            "openai_api_key",
            "azure_openai_api_key",
            "anthropic_api_key",
        ):
            value = getattr(self, name)
            if isinstance(value, SecretStr) and value.get_secret_value().startswith("enc:"):
                plain = decrypt_config_value(value.get_secret_value(), self.secrets_master_key)
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
    def dev_tools_enabled(self) -> bool:
        return self.env != "prod"

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
    def livekit_client_url(self) -> str:
        """WebSocket URL handed to browsers (defaults to the server URL)."""
        return self.livekit_public_url or self.livekit_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
