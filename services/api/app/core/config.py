"""Service settings, read from the environment (and services/api/.env when present).

Secret values may be given in clear text for local development or as an envelope-encrypted
``enc:v1:...`` string produced by ``python -m app.core.secrets encrypt`` (T084); encrypted values
are decrypted at load with ``SECRETS_MASTER_KEY``. Secrets are ``SecretStr`` so they never appear
in reprs, logs or responses.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0123456789abcdef"  # noqa: S105
DEV_WEBHOOK_SECRET = "whsec_dev_fake_stripe_webhook_secret"  # noqa: S105
DEV_MASTER_KEY = "ZGV2LW9ubHktbWFzdGVyLWtleS0zMi1ieXRlcy0hISE="  # 32 bytes, dev only
DEV_SERVICE_TOKEN = "dev-service-token"  # noqa: S105


_API_DIR = Path(__file__).resolve().parents[2]
# Later files win: the repo-root .env, then services/api/.env.
ENV_FILES = (_API_DIR.parent.parent / ".env", _API_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
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

    # Public URLs
    api_base_url: str = "http://localhost:8100"
    web_base_url: str = "http://localhost:5180"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5180"])

    # Identity provider: "local" is the offline dev IdP; "supabase" is production.
    auth_provider: Literal["local", "supabase"] = "local"
    auth_jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    auth_jwks_url: str | None = None
    auth_jwt_audience: str = "authenticated"
    auth_jwt_issuer: str | None = None
    auth_access_token_ttl_s: int = 3600
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
    service_token: SecretStr = SecretStr(DEV_SERVICE_TOKEN)

    # Throttling (R6) and rate limits (R15)
    login_fail_limit: int = 5
    login_fail_ip_limit: int = 20
    login_fail_window_s: int = 900
    quote_rate_limit_per_min: int = 60
    auth_email_rate_limit_per_hour: int = 20

    otel_exporter_otlp_endpoint: str | None = None

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
        ):
            value = getattr(self, name)
            if isinstance(value, SecretStr) and value.get_secret_value().startswith("enc:"):
                plain = decrypt_config_value(value.get_secret_value(), self.secrets_master_key)
                object.__setattr__(self, name, SecretStr(plain))
        if self.env == "prod":
            insecure = [
                n
                for n, default in (
                    ("auth_jwt_secret", DEV_JWT_SECRET),
                    ("stripe_webhook_secret", DEV_WEBHOOK_SECRET),
                    ("secrets_master_key", DEV_MASTER_KEY),
                    ("service_token", DEV_SERVICE_TOKEN),
                )
                if getattr(self, n).get_secret_value() == default
            ]
            if insecure:
                raise ValueError(f"production settings use dev defaults: {', '.join(insecure)}")
            if self.auth_provider == "local" or self.stripe_mode == "fake":
                raise ValueError("production requires AUTH_PROVIDER=supabase and STRIPE_MODE=live")
        if self.auth_provider == "supabase" and not self.supabase_url:
            raise ValueError("AUTH_PROVIDER=supabase requires SUPABASE_URL")
        if self.stripe_mode == "live" and not self.stripe_secret_key:
            raise ValueError("STRIPE_MODE=live requires STRIPE_SECRET_KEY")
        return self

    @property
    def dev_tools_enabled(self) -> bool:
        return self.env != "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
