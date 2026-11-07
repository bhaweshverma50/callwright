"""Session assembly from a frozen AgentVersion snapshot (research R4, R5, R8, R12, R22).

The work is split so most of it is pure and unit-testable without LiveKit:

1. :func:`plan_session` reads the ``RuntimeConfig`` from the claim (AgentConfig plus resolved
   variables and limits) and produces a :class:`~worker.agent.SessionPlan`: one checked
   :class:`VendorSpec` per component, rendered prompt and greeting, turn-taking parameters,
   pronunciation entries and background audio. Unsupported vendors raise
   :class:`UnsupportedVendor` here. A flow's opening comes from the ``FlowRunner`` port.
2. :func:`build_components` turns the plan into framework objects through the adapter registry
   (fakes in the harness, vendor plugins live).
3. :func:`build_session` and :func:`build_agent` create the LiveKit ``AgentSession`` and the
   agent (or the 004 flow entry agent through the ``FlowRunner`` port).

Segment overrides (FR-046) are handled by :class:`OverrideManager`: requests are validated and
clamped to the shared ``controls`` table at once and applied at the next turn boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, cast

from callwright_contract.adapters import Kind
from callwright_contract.variables import render

from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
)
from worker.adapters.stt import language_base
from worker.agent import (
    SessionPlan,
    TtsTextHook,
    TurnDetection,
    auto_stt,
    builtin_instructions,
    make_agent_class,
    resolve_llm,
    resolve_stt,
    resolve_tts,
    tts_gain_for,
)
from worker.audio import entries_from_config, resolve_background_audio
from worker.call_behavior import CallBehavior, behavior_from_config
from worker.flow import FlowComponents, FlowRunner, FlowRuntimeUnavailable
from worker.tools import CallControl, ClampedValue, OverrideResult, SegmentOverrides
from worker.tools.registry import CallTools

if TYPE_CHECKING:
    from callwright_contract.protocol import ControlRange, RuntimeConfig, SttAuto


def resolve_nc(config: Mapping[str, Any], registry: AdapterRegistry) -> VendorSpec:
    """``noise_cancellation: null`` is off (passthrough ``none``)."""
    raw = config.get("noise_cancellation")
    if not raw:
        return registry.check(VendorSpec("nc", "none", "none"))
    return registry.check(VendorSpec("nc", str(raw.get("provider")), raw.get("model")))


def select_turn_detection(stt: VendorSpec, registry: AdapterRegistry) -> TurnDetection:
    """STT built-in end of turn when the model has it, else the semantic model (R5)."""
    return "stt" if registry.builtin_turn_detection(stt) else "semantic"


def turn_handling_options(behavior: CallBehavior, turn_detection: TurnDetection) -> dict[str, Any]:
    """``TurnHandlingOptions`` (livekit-agents 1.8) from the R4 mapping.

    With STT end of turn only ``min_delay`` applies (R4). ``turn_detection`` itself is added by
    :func:`build_session` because the semantic model is a framework object. Endpointing is
    ``fixed``: the dynamic mode only learns a longer ``min_delay`` from pauses it has already
    cut through, and makes the builder's responsiveness value harder to reason about.
    Preemptive generation starts the LLM, and with ``preemptive_tts`` the TTS, on the final
    transcript, so a reply is ready when the turn commits (R4).
    """
    endpointing: dict[str, Any] = {
        "mode": "fixed",
        "min_delay": behavior.endpointing.min_endpointing_delay,
    }
    if turn_detection == "semantic":
        endpointing["max_delay"] = behavior.endpointing.max_endpointing_delay
    interruption: dict[str, Any]
    params = behavior.interruption
    if params.allow_interruptions:
        interruption = {
            "enabled": True,
            "min_duration": params.min_interruption_duration,
            "min_words": params.min_interruption_words,
            "resume_false_interruption": params.resume_false_interruption,
            "false_interruption_timeout": params.false_interruption_timeout,
        }
    else:
        interruption = {"enabled": False}
    preemptive = {"enabled": True, "preemptive_tts": behavior.endpointing.preemptive_tts}
    return {
        "endpointing": endpointing,
        "interruption": interruption,
        "preemptive_generation": preemptive,
    }


def caller_option(runtime: RuntimeConfig) -> Any:
    """012: the option for the caller's saved language when the call should start in it."""
    code = runtime.caller_language
    options = runtime.language_options
    if not code or len(options) < 2 or options[0].code == code:
        return None
    return next((o for o in options[1:] if o.code == code), None)


def in_language(spec: VendorSpec, model: str | None, language: str) -> VendorSpec:
    return VendorSpec(
        spec.kind, spec.provider, model or spec.model, {**spec.options, "language": language}
    )


def own_language_label(runtime: RuntimeConfig, code: str) -> str:
    """The agent language's name from the claim's language options ("Hindi"), else its code."""
    for option in runtime.language_options:
        if option.code in (code, language_base(code)) and option.label:
            return option.label
    return code


def plan_session(
    runtime: RuntimeConfig, registry: AdapterRegistry, flows: FlowRunner | None = None
) -> SessionPlan:
    """Resolve everything a call needs from the frozen config. Raises ``UnsupportedVendor``, and
    ``FlowRuntimeUnavailable`` for a flow agent without a runnable flow (or without ``flows``)."""
    config = runtime.config
    agent_language = str(config["language"])
    language = agent_language
    stt, auto = resolve_stt(
        config,
        registry,
        runtime.stt_auto_rules,
        language=language,
        resolved_model=runtime.stt_resolved_model,
    )
    llm = resolve_llm(config, registry)
    tts = resolve_tts(config, registry, language=language)
    nc = resolve_nc(config, registry)
    reply_language: str | None = None
    caller = caller_option(runtime)
    if caller is not None:
        try:
            stt = registry.check(in_language(stt, caller.stt_model, caller.code))
            tts = registry.check(in_language(tts, caller.tts_model, caller.code))
        except UnsupportedVendor:
            caller = None  # a model this worker cannot run: the call keeps the agent's language
        else:
            language, reply_language = caller.code, caller.label

    behavior = behavior_from_config(config, runtime.limits, runtime.controls)
    turn_detection = select_turn_detection(stt, registry)

    variables = runtime.variables
    instructions = render(str(config.get("prompt") or ""), variables)
    raw_greeting = config.get("begin_message")
    greeting = render(str(raw_greeting), variables).strip() if raw_greeting else None
    start_speaker: Literal["agent", "user"] = (
        "user" if config.get("start_speaker") == "user" else "agent"
    )

    adv: Mapping[str, Any] = config["advanced"]
    background, warnings = resolve_background_audio(config, runtime.background_audio_url)
    is_flow = runtime.agent_type == "flow" or config.get("type") == "flow"
    agent_type: Literal["single_prompt", "flow"] = "flow" if is_flow else "single_prompt"
    if is_flow:
        # 004: the Start node (and Say nodes right after it) is the opening of a flow call.
        if flows is None:
            raise FlowRuntimeUnavailable("flow agents need the flow runtime")
        opening = flows.opening(runtime)
        start_speaker, greeting = opening.start_speaker, opening.greeting
    greeting_language = reply_language if greeting and start_speaker == "agent" else None
    # Speech recognition and the voice follow the agent's language setting, but the prompt may be
    # written in another language: tell the model too (non-English agents; English is the default
    # the prompts are written in). The same "Language rule" line a mid-call switch replaces.
    if reply_language is None and language_base(agent_language) not in ("en", "multi"):
        reply_language = own_language_label(runtime, agent_language)
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
        tts_gain=tts_gain_for(tts, registry),
        background=background,
        warnings=tuple(warnings),
        agent_type=agent_type,
        agent_language=agent_language,
        reply_language=reply_language,
        greeting_language=greeting_language,
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


def build_agent(
    plan: SessionPlan,
    runtime: RuntimeConfig,
    control: CallControl,
    tools: CallTools,
    *,
    flows: FlowRunner | None = None,
    on_tts_text: TtsTextHook | None = None,
    extra_tools: Sequence[Any] = (),
    extra_instructions: str = "",
    flow_components: FlowComponents | None = None,
    **agent_kwargs: Any,
) -> Any:
    """The entry agent with the call's tools (005), or a flow's entry agent from ``flows`` (004).

    ``extra_tools`` and ``extra_instructions`` carry worker-internal tools such as voicemail
    detection (R10); they are added to single-prompt agents and passed to flows as tools.
    """
    if plan.agent_type == "flow":
        if flows is None:
            raise FlowRuntimeUnavailable("flow agents need the flow runtime")
        # Flow nodes carry their own tools (compiled from 005's snapshot) plus the built-in
        # schedule_callback and set_language from the call's tools; worker-internal tools such
        # as voicemail detection are added to every node, with the same built-in rules a
        # single-prompt agent gets (adapted to the flow's own routing).
        return flows.build_agent(
            runtime,
            control,
            plan,
            tools,
            extra_tools=extra_tools,
            extra_instructions="\n\n".join(
                p for p in (builtin_instructions(runtime, flow=True), extra_instructions) if p
            ),
            on_tts_text=on_tts_text,
            components=flow_components,
        )
    agent_cls = make_agent_class()
    return agent_cls(
        plan,
        tools=[*tools.function_tools(), *extra_tools],
        on_tts_text=on_tts_text,
        extra_instructions="\n\n".join(
            p for p in (builtin_instructions(runtime), extra_instructions) if p
        ),
        filler_policy=tools.fillers,
        **agent_kwargs,
    )


def voicemail_tool(report: Callable[[], bool]) -> Any:
    """Internal LLM tool for outbound voicemail detection (R10): calls ``report``."""
    from livekit.agents import function_tool

    from worker.call_behavior import VOICEMAIL_INSTRUCTION, VOICEMAIL_TOOL_NAME

    async def report_answering_machine() -> str:
        return "answering machine noted" if report() else "ignored: outside the detection window"

    return function_tool(
        report_answering_machine, name=VOICEMAIL_TOOL_NAME, description=VOICEMAIL_INSTRUCTION
    )


# --------------------------------------------------------------------------------------------
# Segment overrides (FR-046, research R22)


def clamp_value(path: str, value: float, controls: Sequence[ControlRange]) -> tuple[float, bool]:
    """Clamp to the control's ``[min, max]`` (``path`` is a JSON Pointer) and snap to its step
    grid. Returns (value, was_clamped)."""
    control = next((c for c in controls if c.path == path), None)
    if control is None:
        return value, False
    low, high, step = control.min, control.max, control.step
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
    controls: Sequence[ControlRange]
    stt_auto_rules: Mapping[str, SttAuto]
    on_system_event: Callable[[str, str], Any] | None = None
    current: dict[Kind, VendorSpec] = field(default_factory=dict)
    _pending: dict[Kind, VendorSpec] = field(default_factory=dict)
    _pending_paths: list[str] = field(default_factory=list)
    # 012: the reply language (label) and call language; set_language changes them.
    reply_language: str | None = None
    language: str | None = None
    _pending_language: tuple[str, str | None] | None = None

    def __post_init__(self) -> None:
        if not self.current:
            self.current = {k: self.plan.spec(k) for k in ("stt", "llm", "tts")}
        if self.reply_language is None:
            self.reply_language = self.plan.reply_language
        if self.language is None:
            self.language = self.plan.language

    @property
    def pending(self) -> bool:
        return bool(self._pending) or self._pending_language is not None

    def _emit(self, event: str, detail: str) -> None:
        if self.on_system_event is not None:
            self.on_system_event(event, detail)

    def request(self, overrides: SegmentOverrides) -> OverrideResult:
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
                value, was_clamped = clamp_value(f"/tts/{key}", requested, self.controls)
                if was_clamped:
                    clamped.append(ClampedValue(path, requested, value))
                options[key] = value
                applied.append(path)
            if tts.get("voice_id"):
                options["voice_id"] = tts["voice_id"]
                applied.append("tts.voice_id")
            applied += [f"tts.{k}" for k in ("provider", "model") if tts.get(k)]
            self._stage("tts", VendorSpec("tts", provider, model, options), rejected)

        switch = overrides.get("switch_language")
        if switch:
            code = str(switch.get("code") or "")
            label = switch.get("label")
            # Kept even when switching back to the agent's language: the conversation so far is
            # in another language and the model would otherwise drift back to it.
            self._pending_language = (code, str(label) if label else code)
            applied.append("language")
            spec = base["tts"]
            tts_model = switch.get("tts_model") or spec.model
            self._stage(
                "tts",
                VendorSpec("tts", spec.provider, tts_model, {**spec.options, "language": code}),
                rejected,
            )

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
                    stt_model = auto_stt(self.stt_auto_rules, provider, lang)
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
        if not self.pending:
            self._pending_paths.clear()
            return None
        specs = dict(self._pending)
        paths = tuple(dict.fromkeys(self._pending_paths))
        self.current.update(specs)
        if self._pending_language is not None:
            self.language, self.reply_language = self._pending_language
            self._pending_language = None
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
            tts_gain=tts_gain_for(tts, self.registry),
            language=self.language or self.plan.language,
            reply_language=self.reply_language,
        )
