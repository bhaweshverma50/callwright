"""AgentConfig v1 models, upcasters and API bodies (T011, T033, T088; data-model.md section 4).

The Pydantic models define structure, types and ranges. Ranges for tunable settings come from
the catalog ``controls`` table (one range table, FR-047). Catalog membership, variables, webhook
and cross-field rules live in ``agents/validation.py``; both run on every save, publish and
``POST /v1/agents/validate`` so every problem is reported in one response (SC-004).

Stored versions are never rewritten. ``upcast`` brings any stored config to the current shape on
read (research R4); later format versions register ``UPCASTERS[n]`` to go from ``n`` to ``n + 1``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.voices.catalog import load_catalog as _voice_catalog

CURRENT_SCHEMA_VERSION = 1
AgentType = Literal["single_prompt", "flow"]
AGENT_TYPES: tuple[str, ...] = ("single_prompt", "flow")
DTMF_KEYS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "#", "*")
MAX_PROMPT = 50_000
MAX_GREETING = 1_000
MAX_TOOLS = 25
MAX_KBS = 10
MAX_PRONUNCIATION = 200


def _rng(pointer: str) -> Any:
    """Field constraints from the catalog ``controls`` row for ``pointer``."""
    control = _voice_catalog().control(pointer)
    assert control is not None, f"no control range for {pointer}"
    return Field(ge=float(control.min), le=float(control.max))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRef(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    model: str = Field(min_length=1, max_length=128)


class LlmConfig(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    model: str = Field(min_length=1, max_length=128)
    temperature: float = Field(ge=0, le=2)


class DynamicVariable(_Strict):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    default: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=200)


class SttConfig(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    model: str | None = Field(default=None, max_length=128)


class TtsConfig(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    model: str = Field(min_length=1, max_length=128)
    voice_id: str = Field(min_length=1, max_length=200)
    speed: Annotated[float, _rng("/tts/speed")] = 1.0
    expressiveness: Annotated[float, _rng("/tts/expressiveness")] = 0.9
    volume: Annotated[float, _rng("/tts/volume")] = 1.0


class CallBehavior(_Strict):
    end_on_silence_s: Annotated[int, _rng("/call_behavior/end_on_silence_s")]
    max_duration_s: Annotated[int, _rng("/call_behavior/max_duration_s")]
    ring_duration_ms: Annotated[int, _rng("/call_behavior/ring_duration_ms")]
    interruption_sensitivity: Annotated[float, _rng("/call_behavior/interruption_sensitivity")]
    responsiveness: Annotated[float, _rng("/call_behavior/responsiveness")]


class VoicemailDetection(_Strict):
    enabled: bool
    action: Literal["hang_up", "leave_message"]
    message: str | None = Field(default=None, max_length=500)


class Dtmf(_Strict):
    enabled: bool
    timeout_ms: Annotated[int, _rng("/advanced/dtmf/timeout_ms")] = 2500
    termination_key: Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "#", "*"] | None = "#"
    digits: int = Field(default=10, ge=1, le=99)


class BuiltinSource(_Strict):
    kind: Literal["builtin"]
    id: str = Field(min_length=1, max_length=64)


class UploadSource(_Strict):
    kind: Literal["upload"]
    key: str = Field(min_length=1, max_length=300)


class BackgroundAudio(_Strict):
    enabled: bool
    source: Annotated[BuiltinSource | UploadSource, Field(discriminator="kind")] | None = None
    volume: Annotated[float, _rng("/advanced/background_audio/volume")] = 0.8


class PronunciationEntry(_Strict):
    word: str = Field(min_length=1, max_length=100)
    replacement: str = Field(min_length=1, max_length=200)


class Advanced(_Strict):
    webhook_url: str | None = Field(default=None, max_length=2048)
    webhook_timeout_ms: Annotated[int, _rng("/advanced/webhook_timeout_ms")] = 3000
    voicemail_detection: VoicemailDetection
    dtmf: Dtmf
    background_audio: BackgroundAudio
    analysis_model: ModelRef | None = None
    pronunciation: list[PronunciationEntry] = Field(default_factory=list, max_length=MAX_PRONUNCIATION)
    recording: Literal["inherit", "on", "off"] = "inherit"


class AgentConfigV1(_Strict):
    schema_version: Literal[1]
    type: AgentType
    language: str = Field(min_length=1, max_length=16)
    llm: LlmConfig
    prompt: str = Field(max_length=MAX_PROMPT)
    begin_message: str | None = Field(default=None, max_length=MAX_GREETING)
    start_speaker: Literal["agent", "user"]
    dynamic_variables: list[DynamicVariable] = Field(max_length=50)
    stt: SttConfig
    tts: TtsConfig
    noise_cancellation: ModelRef | None
    call_behavior: CallBehavior
    advanced: Advanced
    tool_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=MAX_TOOLS
    )
    kb_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=MAX_KBS
    )
    flow: dict[str, Any] | None = None
    evals: dict[str, Any] | None = None


# Upcasters (research R4) -----------------------------------------------------------------

UPCASTERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class UnsupportedSchemaVersion(ValueError):
    pass


def upcast(config: dict[str, Any]) -> dict[str, Any]:
    """Return ``config`` in the current format. Never mutates the input.

    Fields added within a format version (``advanced.recording``, T088) read as their default
    when absent, so versions written before the field existed stay readable.
    """
    out = copy.deepcopy(config)
    version = out.get("schema_version", CURRENT_SCHEMA_VERSION)
    if not isinstance(version, int) or version < 1 or version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(f"AgentConfig schema_version {version!r} is not supported")
    while version < CURRENT_SCHEMA_VERSION:
        out = UPCASTERS[version](out)
        version += 1
        out["schema_version"] = version
    advanced = out.get("advanced")
    if isinstance(advanced, dict) and "recording" not in advanced:
        advanced["recording"] = "inherit"
    return out


# API bodies ------------------------------------------------------------------------------

AgentIdStr = Annotated[str, Field(pattern=r"^agt_[0-9A-HJKMNP-TV-Z]{26}$")]


class _NameMixin(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Enter a name.")
        return value.strip() if value is not None else None


class CreateAgentRequest(_NameMixin):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    type: AgentType
    language: str | None = Field(default=None, min_length=1, max_length=16)
    template_id: str | None = Field(default=None, pattern=r"^[a-z0-9-]{3,64}$")
    config: dict[str, Any] | None = None


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: AgentType
    config: dict[str, Any]
    agent_id: AgentIdStr | None = None


class RenameRequest(_NameMixin):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class SaveDraftRequest(_NameMixin):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: dict[str, Any]
    note: str | None = Field(default=None, max_length=500)


class DuplicateRequest(_NameMixin):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
