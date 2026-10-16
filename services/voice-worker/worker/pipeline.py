"""Session assembly from a frozen AgentVersion snapshot (research R4, R5, R8, R12, R22).

The work is split so most of it is pure and unit-testable without LiveKit:

1. :func:`plan_session` reads the ``RuntimeConfig`` from the claim (AgentConfig plus resolved
   variables and limits) and produces a :class:`SessionPlan`: one checked :class:`VendorSpec` per
   component, rendered prompt and greeting, turn-taking parameters, pronunciation entries and
   background audio. Unsupported vendors raise :class:`UnsupportedVendor` here.
2. :func:`build_components` turns the plan into framework objects through the adapter registry
   (fakes in the harness, vendor plugins live).
3. :func:`build_session` and :func:`build_agent` create the LiveKit ``AgentSession`` and the
   agent (or the 004 flow entry agent through the ``FlowRunner`` port).

Segment overrides (FR-046) are handled by :class:`OverrideManager`: requests are validated and
clamped to the shared ``controls`` table at once and applied at the next turn boundary.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, cast

from worker.adapters.registry import (
    AdapterRegistry,
    Kind,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
)
from worker.audio import (
    AudioWarning,
    BackgroundAudioSpec,
    PronunciationEntry,
    PronunciationTransform,
    entries_from_config,
    resolve_background_audio,
)
from worker.call_behavior import CallBehavior, behavior_from_config
from worker.flow import FlowRunner, get_flow_runner
from worker.tools import (
    CallControl,
    ClampedValue,
    OverrideResult,
    SegmentOverrides,
    ToolProvider,
    get_tool_provider,
)

if TYPE_CHECKING:
    from worker.internal_api import ControlRange, RuntimeConfig

# --------------------------------------------------------------------------------------------
# Defaults (002 data-model section 4) used when a config predates a field

DEFAULT_LANGUAGE = "en-US"
DEFAULT_LLM = ("azure_openai", "gpt-5.1")
DEFAULT_STT_PROVIDER = "deepgram"
DEFAULT_TTS_PROVIDER = "elevenlabs"
DEFAULT_NC: Mapping[str, str] = {"provider": "sanas", "model": "vi"}
GENERATED_GREETING_INSTRUCTION = (
    "Open the call with one short, friendly sentence that fits your instructions, then wait "
    "for the caller."
)

# 002 data-model 8.6: the shared range table. The claim's ``controls`` wins when present.
DEFAULT_CONTROLS: Mapping[str, tuple[float, float, float]] = {
    "tts.speed": (0.5, 2.0, 0.1),
    "tts.expressiveness": (0.0, 2.0, 0.1),
    "tts.volume": (0.0, 2.0, 0.05),
}

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*\}\}")


def render_template(text: str, variables: Mapping[str, str]) -> str:
    """Replace ``{{name}}`` placeholders; whitespace inside the braces is tolerated (002).

    The API resolves variables in order call value, agent default, empty (FR-005); a name the
    worker does not know renders empty, never as the raw placeholder.
    """
    return PLACEHOLDER.sub(lambda m: str(variables.get(m.group(1), "")), text)


# --------------------------------------------------------------------------------------------
# Plan


TurnDetection = Literal["stt", "semantic"]


@dataclass(frozen=True)
class SessionPlan:
    language: str
    stt: VendorSpec
    llm: VendorSpec
    tts: VendorSpec
    nc: VendorSpec
    stt_auto: bool
    instructions: str
    greeting: str | None
    start_speaker: Literal["agent", "user"]
    behavior: CallBehavior
    turn_detection: TurnDetection
    turn_handling: Mapping[str, Any]
    pronunciation: tuple[PronunciationEntry, ...]
    tts_gain: float
    background: BackgroundAudioSpec | None
    warnings: tuple[AudioWarning, ...] = ()
    agent_type: Literal["single_prompt", "flow"] = "single_prompt"

    @property
    def generated_greeting(self) -> bool:
        """Agent speaks first with an empty begin message: the LLM writes the opening."""
        return self.start_speaker == "agent" and not self.greeting

    def spec(self, kind: Kind) -> VendorSpec:
        spec: VendorSpec = getattr(self, kind)
        return spec


def _section(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def resolve_stt(
    config: Mapping[str, Any],
    registry: AdapterRegistry,
    *,
    language: str,
    resolved_model: str | None = None,
) -> tuple[VendorSpec, bool]:
    """STT spec with Auto (``model: null``) resolved for the language (FR-045)."""
    raw = _section(config, "stt")
    provider = str(raw.get("provider") or DEFAULT_STT_PROVIDER)
    model = raw.get("model")
    auto = model in (None, "")
    if auto:
        model = resolved_model or registry.resolve_auto_stt(provider, language)
    spec = registry.check(VendorSpec("stt", provider, str(model), {"language": language}))
    return spec, auto


def resolve_llm(config: Mapping[str, Any], registry: AdapterRegistry) -> VendorSpec:
    raw = _section(config, "llm")
    options: dict[str, Any] = {}
    if raw.get("temperature") is not None:
        options["temperature"] = float(raw["temperature"])
    return registry.check(
        VendorSpec(
            "llm",
            str(raw.get("provider") or DEFAULT_LLM[0]),
            str(raw.get("model") or DEFAULT_LLM[1]),
            options,
        )
    )


def resolve_tts(
    config: Mapping[str, Any], registry: AdapterRegistry, *, language: str
) -> VendorSpec:
    raw = _section(config, "tts")
    provider = str(raw.get("provider") or DEFAULT_TTS_PROVIDER)
    entry = registry.entry("tts", provider)
    model = raw.get("model") or entry.default_model
    options: dict[str, Any] = {"language": language}
    for key in ("voice_id", "speed", "expressiveness", "volume"):
        if raw.get(key) is not None:
            options[key] = raw[key]
    return registry.check(VendorSpec("tts", provider, model, options))


def resolve_nc(config: Mapping[str, Any], registry: AdapterRegistry) -> VendorSpec:
    """``noise_cancellation: null`` is off (passthrough ``none``); absent means the default."""
    raw = config.get("noise_cancellation", DEFAULT_NC)
    if not raw:
        return registry.check(VendorSpec("nc", "none", "none"))
    return registry.check(VendorSpec("nc", str(raw.get("provider")), raw.get("model")))


def select_turn_detection(stt: VendorSpec, registry: AdapterRegistry) -> TurnDetection:
    """STT built-in end of turn when the model has it, else the semantic model (R5)."""
    return "stt" if registry.builtin_turn_detection(stt) else "semantic"


def turn_handling_options(behavior: CallBehavior, turn_detection: TurnDetection) -> dict[str, Any]:
    """``TurnHandlingOptions`` (livekit-agents 1.8) from the R4 mapping.

    With STT end of turn only ``min_delay`` applies (R4). ``turn_detection`` itself is added by
    :func:`build_session` because the semantic model is a framework object.
    """
    endpointing: dict[str, Any] = {"min_delay": behavior.endpointing.min_endpointing_delay}
    if turn_detection == "semantic":
        endpointing["max_delay"] = behavior.endpointing.max_endpointing_delay
    interruption: dict[str, Any]
    if behavior.interruption.allow_interruptions:
        interruption = {
            "enabled": True,
            "min_duration": behavior.interruption.min_interruption_duration,
            "min_words": behavior.interruption.min_interruption_words,
        }
    else:
        interruption = {"enabled": False}
    return {"endpointing": endpointing, "interruption": interruption}


def tts_gain_for(tts: VendorSpec) -> float:
    """Output gain the worker applies when the vendor has no native volume control."""
    volume = float(tts.options.get("volume", 1.0))
    if _adapter_native_volume(tts):
        return 1.0
    return volume


def _adapter_native_volume(tts: VendorSpec) -> bool:
    import importlib

    try:
        module = importlib.import_module(f"worker.adapters.tts.{tts.provider}")
    except ImportError:
        return False
    fn = getattr(module, "native_volume", None)
    return bool(fn(tts.model)) if callable(fn) else False


def plan_session(runtime: RuntimeConfig, registry: AdapterRegistry) -> SessionPlan:
    """Resolve everything a call needs from the frozen config. Raises ``UnsupportedVendor``."""
    config = runtime.config
    language = str(config.get("language") or DEFAULT_LANGUAGE)
    stt, auto = resolve_stt(
        config, registry, language=language, resolved_model=runtime.stt_resolved_model
    )
    llm = resolve_llm(config, registry)
    tts = resolve_tts(config, registry, language=language)
    nc = resolve_nc(config, registry)

    behavior = behavior_from_config(config, runtime.limits.model_dump())
    turn_detection = select_turn_detection(stt, registry)

    variables = runtime.variables
    instructions = render_template(str(config.get("prompt") or ""), variables)
    raw_greeting = config.get("begin_message")
    greeting = render_template(str(raw_greeting), variables).strip() if raw_greeting else None
    start_speaker: Literal["agent", "user"] = (
        "user" if config.get("start_speaker") == "user" else "agent"
    )

    adv = _section(config, "advanced")
    background, warnings = resolve_background_audio(config, runtime.background_audio_url)
    is_flow = runtime.agent_type == "flow" or config.get("type") == "flow"
    agent_type: Literal["single_prompt", "flow"] = "flow" if is_flow else "single_prompt"
    return SessionPlan(
        language=language,
        stt=stt,
        llm=llm,
        tts=tts,
        nc=nc,
        stt_auto=auto,
        instructions=instructions,
        greeting=greeting or None,
        start_speaker=start_speaker,
        behavior=behavior,
        turn_detection=turn_detection,
        turn_handling=turn_handling_options(behavior, turn_detection),
        pronunciation=tuple(entries_from_config(adv.get("pronunciation"))),
        tts_gain=tts_gain_for(tts),
        background=background,
        warnings=tuple(warnings),
        agent_type=agent_type,
    )


# --------------------------------------------------------------------------------------------
# Components and session


@dataclass
class SessionComponents:
    stt: Any
    llm: Any
    tts: Any
    nc: Any

    def get(self, kind: Kind) -> Any:
        return getattr(self, kind)

    def set(self, kind: Kind, value: Any) -> None:
        setattr(self, kind, value)


def build_components(
    plan: SessionPlan, registry: AdapterRegistry, creds: Mapping[str, Mapping[str, str]]
) -> SessionComponents:
    def one(kind: Kind) -> Any:
        spec = plan.spec(kind)
        return registry.build(spec, creds.get(spec.provider, {}))

    return SessionComponents(stt=one("stt"), llm=one("llm"), tts=one("tts"), nc=one("nc"))


def vendor_conn_options(retry_window_s: float = 5.0) -> Any:
    """Connection options that keep each vendor's retries inside the window (FR-026, T056)."""
    from livekit.agents import APIConnectOptions
    from livekit.agents.voice.agent_session import SessionConnectOptions

    opts = APIConnectOptions(max_retry=2, retry_interval=retry_window_s / 4, timeout=10.0)
    return SessionConnectOptions(
        stt_conn_options=opts, llm_conn_options=opts, tts_conn_options=opts
    )


def build_session(
    plan: SessionPlan,
    components: SessionComponents,
    *,
    vad: Any,
    turn_detector: Any = None,
    retry_window_s: float = 5.0,
) -> Any:
    """LiveKit ``AgentSession`` for the plan. ``turn_detector`` is the semantic model."""
    from livekit.agents import AgentSession

    turn_handling: dict[str, Any] = dict(plan.turn_handling)
    if plan.turn_detection == "stt":
        turn_handling["turn_detection"] = "stt"
    elif turn_detector is not None:
        turn_handling["turn_detection"] = turn_detector
    return AgentSession(
        stt=components.stt,
        llm=components.llm,
        tts=components.tts,
        vad=vad,
        turn_handling=turn_handling,  # type: ignore[arg-type]
        # Silence is handled by our InactivityTimer (R9), which also tracks the agent.
        user_away_timeout=None,
        conn_options=vendor_conn_options(retry_window_s),
    )


def vendor_error_diagnostic(source: Any, plan: SessionPlan) -> str:
    """``vendor_error:<kind>/<provider>`` for an unrecoverable component error (T056)."""
    from livekit.agents import llm as lk_llm
    from livekit.agents import stt as lk_stt
    from livekit.agents import tts as lk_tts

    kind: Kind | None = None
    if isinstance(source, lk_stt.STT):
        kind = "stt"
    elif isinstance(source, lk_llm.LLM):
        kind = "llm"
    elif isinstance(source, lk_tts.TTS):
        kind = "tts"
    if kind is None:
        return "vendor_error:runtime/unknown"
    return f"vendor_error:{kind}/{plan.spec(kind).provider}"


TtsTextHook = Callable[[str], None]


async def pronounce(
    text: AsyncIterable[str], transform: PronunciationTransform, on_text: TtsTextHook | None
) -> AsyncIterator[str]:
    """Pronunciation transform for the TTS node; ``on_text`` sees what is sent to TTS (R7)."""
    async for chunk in transform.stream(text):
        if on_text is not None:
            on_text(chunk)
        yield chunk


def make_agent_class() -> type[Any]:
    """The single-prompt LiveKit agent. Built lazily so pure tests never import LiveKit."""
    from livekit.agents import Agent

    class CallwrightAgent(Agent):
        """Applies pronunciation and output gain in the TTS node; transcript keeps LLM text."""

        def __init__(
            self,
            plan: SessionPlan,
            *,
            tools: Sequence[Any] = (),
            on_tts_text: TtsTextHook | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(instructions=plan.instructions or " ", tools=list(tools), **kwargs)
            self.plan = plan
            self._on_tts_text = on_tts_text

        async def tts_node(self, text: AsyncIterable[str], model_settings: Any) -> Any:
            transform = PronunciationTransform(self.plan.pronunciation)
            frames = Agent.default.tts_node(
                self, pronounce(text, transform, self._on_tts_text), model_settings
            )
            if self.plan.tts_gain == 1.0:
                async for frame in frames:
                    yield frame
                return
            from worker.audio import scale_frame

            async for frame in frames:
                yield scale_frame(frame, self.plan.tts_gain)

    return CallwrightAgent


def build_agent(
    plan: SessionPlan,
    runtime: RuntimeConfig,
    control: CallControl,
    *,
    tool_provider: ToolProvider | None = None,
    flow_runner: FlowRunner | None = None,
    on_tts_text: TtsTextHook | None = None,
    **agent_kwargs: Any,
) -> Any:
    """The entry agent: tools from 005's provider, flows from 004's runner (FR-024)."""
    tools = list((tool_provider or get_tool_provider()).tools_for(runtime, control))
    if plan.agent_type == "flow":
        return (flow_runner or get_flow_runner()).build_agent(runtime, control, tools)
    agent_cls = make_agent_class()
    return agent_cls(plan, tools=tools, on_tts_text=on_tts_text, **agent_kwargs)


# --------------------------------------------------------------------------------------------
# Segment overrides (FR-046, research R22)


def _controls_table(
    controls: Sequence[ControlRange] | None,
) -> dict[str, tuple[float, float, float | None]]:
    table: dict[str, tuple[float, float, float | None]] = {
        k: (lo, hi, step) for k, (lo, hi, step) in DEFAULT_CONTROLS.items()
    }
    for row in controls or ():
        table[row.path] = (row.min, row.max, row.step)
    return table


def clamp_value(
    path: str, value: float, table: Mapping[str, tuple[float, float, float | None]]
) -> tuple[float, bool]:
    """Clamp to ``[min, max]`` and snap to the step grid. Returns (value, was_clamped)."""
    if path not in table:
        return value, False
    low, high, step = table[path]
    applied = max(low, min(high, value))
    if step:
        applied = low + round((applied - low) / step) * step
        applied = max(low, min(high, applied))
    applied = round(applied, 6)
    return applied, applied != round(value, 6)


@dataclass(frozen=True)
class OverrideSwap:
    """What changed at a turn boundary; ``kinds`` need new components."""

    kinds: tuple[Kind, ...]
    paths: tuple[str, ...]
    specs: Mapping[Kind, VendorSpec]


@dataclass
class OverrideManager:
    """Validates, clamps and stages segment overrides; applies them between turns."""

    plan: SessionPlan
    registry: AdapterRegistry
    controls: Sequence[ControlRange] | None = None
    on_system_event: Callable[[str, str], Any] | None = None
    current: dict[Kind, VendorSpec] = field(default_factory=dict)
    _pending: dict[Kind, VendorSpec] = field(default_factory=dict)
    _pending_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.current:
            self.current = {k: self.plan.spec(k) for k in ("stt", "llm", "tts")}

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    def _emit(self, event: str, detail: str) -> None:
        if self.on_system_event is not None:
            self.on_system_event(event, detail)

    def request(self, overrides: SegmentOverrides) -> OverrideResult:
        table = _controls_table(self.controls)
        clamped: list[ClampedValue] = []
        applied: list[str] = []
        rejected: list[str] = []
        base = {k: self._pending.get(k, v) for k, v in self.current.items()}

        llm = overrides.get("llm")
        if llm:
            spec = base["llm"]
            options = dict(spec.options)
            if llm.get("temperature") is not None:
                options["temperature"] = float(llm["temperature"])
                applied.append("llm.temperature")
            candidate = VendorSpec(
                "llm", llm.get("provider", spec.provider), llm.get("model", spec.model), options
            )
            applied += [f"llm.{k}" for k in ("provider", "model") if llm.get(k)]
            self._stage("llm", candidate, rejected)

        tts_raw = overrides.get("tts")
        if tts_raw:
            tts = cast(Mapping[str, Any], tts_raw)
            spec = base["tts"]
            options = dict(spec.options)
            provider = str(tts.get("provider", spec.provider))
            model = tts.get("model") or (spec.model if provider == spec.provider else None)
            if model is None:
                try:
                    model = self.registry.entry("tts", provider).default_model
                except UnsupportedVendor:
                    model = None
            for key in ("speed", "expressiveness", "volume"):
                if tts.get(key) is None:
                    continue
                path = f"tts.{key}"
                requested = float(tts[key])
                value, was_clamped = clamp_value(path, requested, table)
                if was_clamped:
                    clamped.append(ClampedValue(path, requested, value))
                options[key] = value
                applied.append(path)
            if tts.get("voice_id"):
                options["voice_id"] = tts["voice_id"]
                applied.append("tts.voice_id")
            applied += [f"tts.{k}" for k in ("provider", "model") if tts.get(k)]
            self._stage("tts", VendorSpec("tts", provider, model, options), rejected)

        stt_raw = overrides.get("stt")
        language = overrides.get("language")
        if stt_raw or language:
            stt = cast(Mapping[str, Any], stt_raw or {})
            spec = base["stt"]
            old_lang = str(spec.options.get("language", self.plan.language))
            lang = str(stt.get("language") or language or old_lang)
            provider = str(stt.get("provider", spec.provider))
            stt_model: str | None
            if "model" in stt:
                stt_model = stt["model"]  # None is Auto
            elif provider != spec.provider or (lang != old_lang and self.plan.stt_auto):
                stt_model = None  # re-resolve Auto for the new provider or language
            else:
                stt_model = spec.model
            try:
                if stt_model is None:
                    stt_model = self.registry.resolve_auto_stt(provider, lang)
            except (UnsupportedVendor, UnsupportedLanguage):
                rejected.append("stt")
            else:
                candidate = VendorSpec(
                    "stt", provider, stt_model, {**spec.options, "language": lang}
                )
                applied += [f"stt.{k}" for k in ("provider", "model", "language") if k in stt]
                if language and "language" not in stt:
                    applied.append("language")
                self._stage("stt", candidate, rejected)

        for c in clamped:
            self._emit("override_clamped", f"{c.path} {c.requested} -> {c.applied}")
        accepted = tuple(dict.fromkeys(p for p in applied if p.split(".")[0] not in rejected))
        self._pending_paths += list(accepted)
        return OverrideResult(
            applied_paths=accepted,
            clamped=tuple(clamped),
            rejected=tuple(rejected),
            pending=self.pending,
        )

    def _stage(self, kind: Kind, spec: VendorSpec, rejected: list[str]) -> None:
        try:
            checked = self.registry.check(spec)
        except UnsupportedVendor:
            rejected.append(kind)
            return
        if checked != self.current[kind]:
            self._pending[kind] = checked

    def apply_pending(self) -> OverrideSwap | None:
        """Called at a turn boundary. Returns the swap, or None when nothing is staged."""
        if not self._pending:
            self._pending_paths.clear()
            return None
        specs = dict(self._pending)
        paths = tuple(dict.fromkeys(self._pending_paths))
        self.current.update(specs)
        self._pending.clear()
        self._pending_paths.clear()
        kinds = tuple(k for k in ("stt", "llm", "tts") if k in specs)
        self._emit("segment_override", ", ".join(paths) or ", ".join(kinds))
        return OverrideSwap(kinds=kinds, paths=paths, specs=specs)

    def plan_for_current(self) -> SessionPlan:
        """The plan with the current specs (for building a replacement agent)."""
        tts = self.current["tts"]
        return replace(
            self.plan,
            stt=self.current["stt"],
            llm=self.current["llm"],
            tts=tts,
            tts_gain=tts_gain_for(tts),
        )
