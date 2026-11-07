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

# The Azure OpenAI resource agents run on when a key is set without AZURE_OPENAI_ENDPOINT.
AZURE_OPENAI_DEFAULT_ENDPOINT = "https://callwright.openai.azure.com"


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    role: Literal["live", "textsim"] = Field("live", alias="WORKER_ROLE")
    agent_name: str = Field("callwright-voice", alias="WORKER_AGENT_NAME")
    health_port: int = Field(8190, alias="WORKER_HEALTH_PORT")
    # Agent server capacity (unset: the framework defaults, 12 prewarmed job processes and a 0.7
    # load threshold in production). A small VM shares its CPU and memory with LiveKit, so the
    # hosted deployment sets fewer idle processes and a higher threshold (deploy/vm/render-env.sh).
    num_idle_processes: int | None = Field(None, alias="WORKER_NUM_IDLE_PROCESSES", ge=0)
    load_threshold: float | None = Field(None, alias="WORKER_LOAD_THRESHOLD", gt=0, le=1)

    # 008 text simulations (WORKER_ROLE=textsim): the arq queue on the platform Redis, jobs run
    # at once per process and the longest a single simulation may take.
    redis_url: str = Field("redis://localhost:56379/0", alias="REDIS_URL")
    textsim_max_jobs: int = Field(10, alias="TEXTSIM_MAX_JOBS", ge=1)
    textsim_job_timeout_s: int = Field(900, alias="TEXTSIM_JOB_TIMEOUT_S", ge=30)

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
    # 005 warm transfers dial the destination on this trunk unless the call has its own (010).
    sip_outbound_trunk_id: str = Field("", alias="SIP_OUTBOUND_TRUNK_ID")

    deepgram_api_key: SecretStr = Field(SecretStr(""), alias="DEEPGRAM_API_KEY")
    assemblyai_api_key: SecretStr = Field(SecretStr(""), alias="ASSEMBLYAI_API_KEY")
    sarvam_api_key: SecretStr = Field(SecretStr(""), alias="SARVAM_API_KEY")
    openai_api_key: SecretStr = Field(SecretStr(""), alias="OPENAI_API_KEY")
    # OpenAI ``service_tier`` for agent replies (unset: the account default). ``priority`` cuts
    # time to first token by about 200 to 300 ms for twice the token price.
    openai_service_tier: str = Field("", alias="OPENAI_SERVICE_TIER")
    azure_openai_api_key: SecretStr = Field(SecretStr(""), alias="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str = Field("", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_version: str = Field("", alias="AZURE_OPENAI_API_VERSION")
    # Claude models (003 T069). Without it the anthropic provider is unavailable on this
    # deployment: live calls are refused and text simulations use the offline scripts.
    anthropic_api_key: SecretStr = Field(SecretStr(""), alias="ANTHROPIC_API_KEY")
    eleven_api_key: SecretStr = Field(SecretStr(""), alias="ELEVEN_API_KEY")
    cartesia_api_key: SecretStr = Field(SecretStr(""), alias="CARTESIA_API_KEY")
    fishaudio_api_key: SecretStr = Field(SecretStr(""), alias="FISHAUDIO_API_KEY")
    sanas_api_key: SecretStr = Field(SecretStr(""), alias="SANAS_API_KEY")
    ai_coustics_api_key: SecretStr = Field(SecretStr(""), alias="AI_COUSTICS_API_KEY")

    def azure_openai_falls_back_to_openai(self) -> bool:
        """True when Azure OpenAI is not configured (no key or no endpoint) but an OpenAI key is.

        Agents select the LLM by ``llm.provider`` in their config, and the platform default
        (and the launch templates) is ``azure_openai``. A deployment that only holds
        ``OPENAI_API_KEY`` (the hosted demo) then runs those agents' models (the same ids,
        ``gpt-5.1``, ``gpt-5.2``, ``gpt-5-mini``) on OpenAI directly; an agent can also pick
        ``{"provider": "openai"}`` itself. Both providers are priced the same per minute."""
        azure_ready = bool(
            self.azure_openai_api_key.get_secret_value() and self.azure_openai_endpoint
        )
        return not azure_ready and bool(self.openai_api_key.get_secret_value())

    def vendor_credentials(self) -> dict[str, dict[str, str]]:
        """Credentials per provider id, as passed to adapter ``build(spec, creds)``."""
        azure: dict[str, str] = {
            "api_key": self.azure_openai_api_key.get_secret_value(),
            "endpoint": self.azure_openai_endpoint or AZURE_OPENAI_DEFAULT_ENDPOINT,
            "api_version": self.azure_openai_api_version,
        }
        if self.azure_openai_falls_back_to_openai():
            azure["fallback_openai_api_key"] = self.openai_api_key.get_secret_value()
            azure["service_tier"] = self.openai_service_tier
        return {
            "deepgram": {"api_key": self.deepgram_api_key.get_secret_value()},
            "assemblyai": {"api_key": self.assemblyai_api_key.get_secret_value()},
            "sarvam": {"api_key": self.sarvam_api_key.get_secret_value()},
            "openai": {
                "api_key": self.openai_api_key.get_secret_value(),
                "service_tier": self.openai_service_tier,
            },
            "azure_openai": azure,
            "anthropic": {"api_key": self.anthropic_api_key.get_secret_value()},
            "elevenlabs": {"api_key": self.eleven_api_key.get_secret_value()},
            "cartesia": {"api_key": self.cartesia_api_key.get_secret_value()},
            "fishaudio": {"api_key": self.fishaudio_api_key.get_secret_value()},
            "sanas": {"api_key": self.sanas_api_key.get_secret_value()},
            "ai_coustics": {"api_key": self.ai_coustics_api_key.get_secret_value()},
            "none": {},
        }


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()
