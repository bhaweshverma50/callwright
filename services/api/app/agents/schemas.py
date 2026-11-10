"""AgentConfig v1 models, upcasters and API bodies (T011, T033, T088; data-model.md section 4).

The Pydantic models define structure, types and ranges. Ranges for tunable settings come from
the catalog ``controls`` table (one range table, FR-047). Catalog membership, variables, webhook
and cross-field rules live in ``agents/validation.py``; both run on every save, publish and
``POST /v1/agents/validate`` so every problem is reported in one response (SC-004).

Stored versions are never rewritten. ``upcast`` brings any stored config to the current shape on
read (research R4).
"""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal

from callwright_contract.protocol import MAX_KNOWLEDGE_BASES
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.defaults import ADVANCED_DEFAULTS, CURRENT_SCHEMA_VERSION, TTS_TUNING_DEFAULTS
from app.agents.variables import MAX_DESCRIPTION_CHARS, MAX_VALUE_CHARS, MAX_VARIABLES, NAME_PATTERN
from app.voices.catalog import load_catalog as _voice_catalog

AgentType = Literal["single_prompt", "flow"]
NAME_MAX = 80  # agents.name CHECK (migration s002_0001); a flow's name is its agent's name
MAX_PROMPT = 50_000
MAX_GREETING = 1_000
MAX_TOOLS = 25
MAX_PRONUNCIATION = 200
MAX_SWITCH_LANGUAGES = 30
# Ranges the catalog ``controls`` table does not hold: temperature per model is in
# llms/catalog.yaml, this is only the outer bound.
TEMPERATURE_RANGE = (0, 2)
DTMF_DIGITS_RANGE = (1, 99)
_DTMF = ADVANCED_DEFAULTS["dtmf"]


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
    temperature: float = Field(ge=TEMPERATURE_RANGE[0], le=TEMPERATURE_RANGE[1])


class DynamicVariable(_Strict):
    name: str = Field(pattern=NAME_PATTERN)
    default: str | None = Field(default=None, max_length=MAX_VALUE_CHARS)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)


class SttConfig(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    model: str | None = Field(default=None, max_length=128)


class TtsConfig(_Strict):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    model: str = Field(min_length=1, max_length=128)
    voice_id: str = Field(min_length=1, max_length=200)
    speed: Annotated[float, _rng("/tts/speed")] = TTS_TUNING_DEFAULTS["speed"]
    expressiveness: Annotated[float, _rng("/tts/expressiveness")] = TTS_TUNING_DEFAULTS["expressiveness"]
    volume: Annotated[float, _rng("/tts/volume")] = TTS_TUNING_DEFAULTS["volume"]


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
    timeout_ms: Annotated[int, _rng("/advanced/dtmf/timeout_ms")] = _DTMF["timeout_ms"]
    termination_key: Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "#", "*"] | None = _DTMF[
        "termination_key"
    ]
    digits: int = Field(default=_DTMF["digits"], ge=DTMF_DIGITS_RANGE[0], le=DTMF_DIGITS_RANGE[1])


class BuiltinSource(_Strict):
    kind: Literal["builtin"]
    id: str = Field(min_length=1, max_length=64)


class UploadSource(_Strict):
    kind: Literal["upload"]
    key: str = Field(min_length=1, max_length=300)


class BackgroundAudio(_Strict):
    enabled: bool
    source: Annotated[BuiltinSource | UploadSource, Field(discriminator="kind")] | None = None
    volume: Annotated[float, _rng("/advanced/background_audio/volume")] = ADVANCED_DEFAULTS[
        "background_audio"
    ]["volume"]


class PronunciationEntry(_Strict):
    word: str = Field(min_length=1, max_length=100)
    replacement: str = Field(min_length=1, max_length=200)


class LanguageSwitching(_Strict):
    """Caller language (012): switch to the caller's language and remember it per caller."""

    enabled: bool = ADVANCED_DEFAULTS["language_switching"]["enabled"]
    languages: list[Annotated[str, Field(min_length=2, max_length=16)]] = Field(
        default_factory=list, max_length=MAX_SWITCH_LANGUAGES
    )


class Advanced(_Strict):
    webhook_url: str | None = Field(default=None, max_length=2048)
    webhook_timeout_ms: Annotated[int, _rng("/advanced/webhook_timeout_ms")] = ADVANCED_DEFAULTS[
        "webhook_timeout_ms"
    ]
    voicemail_detection: VoicemailDetection
    dtmf: Dtmf
    background_audio: BackgroundAudio
    analysis_model: ModelRef | None = None
    pronunciation: list[PronunciationEntry] = Field(default_factory=list, max_length=MAX_PRONUNCIATION)
    recording: Literal["inherit", "on", "off"] = ADVANCED_DEFAULTS["recording"]
    language_switching: LanguageSwitching = Field(default_factory=LanguageSwitching)


class AgentConfigV1(_Strict):
    schema_version: Literal[1]
    type: AgentType
    language: str = Field(min_length=1, max_length=16)
    llm: LlmConfig
    prompt: str = Field(max_length=MAX_PROMPT)
    begin_message: str | None = Field(default=None, max_length=MAX_GREETING)
    start_speaker: Literal["agent", "user"]
    dynamic_variables: list[DynamicVariable] = Field(max_length=MAX_VARIABLES)
    stt: SttConfig
    tts: TtsConfig
    noise_cancellation: ModelRef | None
    call_behavior: CallBehavior
    advanced: Advanced
    tool_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=MAX_TOOLS
    )
    kb_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=MAX_KNOWLEDGE_BASES
    )
    flow: dict[str, Any] | None = None
    evals: dict[str, Any] | None = None


class UnsupportedSchemaVersion(ValueError):
    pass


def upcast(config: dict[str, Any]) -> dict[str, Any]:
    """Return ``config`` in the current format. Never mutates the input.

    Fields added within a format version (``advanced.recording``, T088;
    ``advanced.language_switching``, 012) read as their default when absent, so versions written
    before the field existed stay readable.
    """
    out = copy.deepcopy(config)
    version = out.get("schema_version", CURRENT_SCHEMA_VERSION)
    if not isinstance(version, int) or version < 1 or version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(f"AgentConfig schema_version {version!r} is not supported")
    advanced = out.get("advanced")
    if isinstance(advanced, dict):
        for key in ("recording", "language_switching"):
            advanced.setdefault(key, copy.deepcopy(ADVANCED_DEFAULTS[key]))
    return out


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

    name: str = Field(min_length=1, max_length=NAME_MAX)
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

    name: str = Field(min_length=1, max_length=NAME_MAX)


class SaveDraftRequest(_NameMixin):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    config: dict[str, Any]
    note: str | None = Field(default=None, max_length=500)


class DuplicateRequest(_NameMixin):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    version_id: str | None = Field(default=None, pattern=r"^agv_[0-9A-HJKMNP-TV-Z]{26}$")
