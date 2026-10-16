"""Worker settings from the environment (``services/voice-worker/.env`` in development).

The worker never holds database or storage credentials (003 plan constraints): only the internal
API URL and service token, LiveKit credentials and the platform's vendor keys. Vendor keys are
optional; without them adapters still build (with empty keys) and the offline harness uses fakes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    role: Literal["live", "textsim"] = Field("live", alias="WORKER_ROLE")
    agent_name: str = Field("callwright-voice", alias="WORKER_AGENT_NAME")
    health_port: int = Field(8190, alias="WORKER_HEALTH_PORT")

    internal_api_url: str = Field(
        "http://localhost:8100/v1/internal", alias="CALLWRIGHT_INTERNAL_API_URL"
    )
    service_token: SecretStr = Field(
        SecretStr("dev-service-token"), alias="CALLWRIGHT_SERVICE_TOKEN"
    )
    heartbeat_interval_s: float = Field(10.0, alias="WORKER_HEARTBEAT_INTERVAL_S")
    http_timeout_s: float = Field(5.0, alias="WORKER_HTTP_TIMEOUT_S")
    events_max_attempts: int = Field(5, alias="WORKER_EVENTS_MAX_ATTEMPTS")
    events_backoff_base_s: float = Field(0.5, alias="WORKER_EVENTS_BACKOFF_BASE_S")
    vendor_retry_window_s: float = Field(5.0, alias="WORKER_VENDOR_RETRY_WINDOW_S")
    # Tracing (T106): none (default, no-op), console, or otlp (standard OTEL_EXPORTER_OTLP_*).
    otel_exporter: Literal["none", "console", "otlp"] = Field(
        "none", alias="CALLWRIGHT_OTEL_EXPORTER"
    )

    livekit_url: str = Field("ws://localhost:7880", alias="LIVEKIT_URL")
    livekit_api_key: SecretStr = Field(SecretStr("devkey"), alias="LIVEKIT_API_KEY")
    livekit_api_secret: SecretStr = Field(SecretStr("secret"), alias="LIVEKIT_API_SECRET")

    deepgram_api_key: SecretStr = Field(SecretStr(""), alias="DEEPGRAM_API_KEY")
    assemblyai_api_key: SecretStr = Field(SecretStr(""), alias="ASSEMBLYAI_API_KEY")
    sarvam_api_key: SecretStr = Field(SecretStr(""), alias="SARVAM_API_KEY")
    openai_api_key: SecretStr = Field(SecretStr(""), alias="OPENAI_API_KEY")
    azure_openai_api_key: SecretStr = Field(SecretStr(""), alias="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str = Field("", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_version: str = Field("", alias="AZURE_OPENAI_API_VERSION")
    eleven_api_key: SecretStr = Field(SecretStr(""), alias="ELEVEN_API_KEY")
    cartesia_api_key: SecretStr = Field(SecretStr(""), alias="CARTESIA_API_KEY")
    fishaudio_api_key: SecretStr = Field(SecretStr(""), alias="FISHAUDIO_API_KEY")
    sanas_api_key: SecretStr = Field(SecretStr(""), alias="SANAS_API_KEY")
    # Sanas NC contract (worker/adapters/nc/sanas.py); unused until the vendor SDK is wired.
    sanas_endpoint: str = Field("", alias="SANAS_ENDPOINT")
    sanas_sample_rate: int = Field(16000, alias="SANAS_SAMPLE_RATE")
    sanas_max_latency_ms: float = Field(20.0, alias="SANAS_MAX_LATENCY_MS")
    ai_coustics_api_key: SecretStr = Field(SecretStr(""), alias="AI_COUSTICS_API_KEY")

    def vendor_credentials(self) -> dict[str, dict[str, str]]:
        """Credentials per provider id, as passed to adapter ``build(spec, creds)``."""
        return {
            "deepgram": {"api_key": self.deepgram_api_key.get_secret_value()},
            "assemblyai": {"api_key": self.assemblyai_api_key.get_secret_value()},
            "sarvam": {"api_key": self.sarvam_api_key.get_secret_value()},
            "openai": {"api_key": self.openai_api_key.get_secret_value()},
            "azure_openai": {
                "api_key": self.azure_openai_api_key.get_secret_value(),
                "endpoint": self.azure_openai_endpoint,
                "api_version": self.azure_openai_api_version,
            },
            "elevenlabs": {"api_key": self.eleven_api_key.get_secret_value()},
            "cartesia": {"api_key": self.cartesia_api_key.get_secret_value()},
            "fishaudio": {"api_key": self.fishaudio_api_key.get_secret_value()},
            "sanas": {
                "api_key": self.sanas_api_key.get_secret_value(),
                "endpoint": self.sanas_endpoint,
                "sample_rate": str(self.sanas_sample_rate),
                "max_latency_ms": str(self.sanas_max_latency_ms),
            },
            "ai_coustics": {"api_key": self.ai_coustics_api_key.get_secret_value()},
            "none": {},
        }


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()
