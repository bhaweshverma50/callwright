"""The agent a call runs and what it is told (003 research R4, R7, R12; 005, 011, 012).

:class:`SessionPlan` is everything resolved for one call (vendors, prompt, greeting, turn-taking,
pronunciation, output gain). The ``resolve_*`` functions turn an agent or flow-node config into
checked vendor specs. The prompt is assembled here: the agent's instructions, the voice style and
ending rules, the callback rule with the caller's local time and the language rules.
:func:`make_agent_class` builds the LiveKit agent that applies pronunciation and output gain in
its TTS node and says a filler line before a lookup tool runs. Single-prompt agents
(``worker.pipeline``) and flow nodes (``worker.flow.runtime``) are both built from it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from callwright_contract.adapters import Kind
from callwright_contract.values import clock
from callwright_contract.variables import CALLBACK_NOTE, local_now

from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
)
from worker.adapters.stt import language_base
from worker.audio import (
    AudioWarning,
    BackgroundAudioSpec,
    PronunciationEntry,
    PronunciationTransform,
)
from worker.call_behavior import CallBehavior
from worker.language import FOLLOW_CALLER_LANGUAGE, set_language_instruction, with_reply_language

if TYPE_CHECKING:
    from callwright_contract.protocol import RuntimeConfig, SttAuto

GENERATED_GREETING_INSTRUCTION = (
    "Open the call with one short, friendly sentence that fits your instructions, then wait "
    "for the caller."
)

# Appended to every single-prompt agent. Speech starts once the first sentence is complete, so
# a short opening sentence is heard sooner; markup is read out literally by TTS.
VOICE_STYLE_INSTRUCTION = (
    "Your replies are spoken aloud on a live call, so talk the way a warm, attentive person talks "
    "on the phone, not the way people write. Start each reply with a short sentence. Keep replies "
    "short, usually under 35 words, and end with at most one question. Never list options or "
    "examples: ask an open question, or offer two choices at the very most. Use contractions and "
    'everyday words, and react to what the caller just said before moving on ("Got it.", "Oh, '
    'that\'s tough.", "Okay, so..."), without opening every reply the same way. Match the '
    "caller's mood and pace: calm and gentle when they are upset, brisk when they are in a hurry. "
    "Never use lists, headings, markdown, emojis or line breaks."
)

# Part of both ending rules. On a lab call the caller said "I'm getting a call. Can you call me in
# five minutes?"; speech recognition finalised the first sentence as its own turn and the model
# hung up on it (7 of 8 times in a replay) instead of asking how to follow up.
CALLER_HAS_TO_GO = (
    "A caller who says they have to go or is being interrupted (another call coming in, a "
    'meeting, someone at the door, "hold on") has not ended the conversation, and a line that '
    "sounds unfinished is not a goodbye. If they have not said how to follow up, do not hang up: "
    "ask in one short question whether they would like a call back, and when. If they ask to be "
    "called back, book it with schedule_callback first. If they only ask you to hold, say you "
    "will wait."
)

# Appended to every single-prompt agent, which always has an end_call tool (tools/registry.py).
ENDING_INSTRUCTION = (
    "When the conversation is over, end it the way a good receptionist would: in one or two short "
    "sentences confirm what was agreed or what happens next (for example when you will call back), "
    "then say goodbye and call end_call in that same reply. "
    + CALLER_HAS_TO_GO
    + " Never promise something you cannot do. Always say your goodbye out loud, in the reply "
    "text or in end_call's goodbye argument. Do not wait for the caller to say goodbye back. If "
    "the caller speaks again after your goodbye only to thank you or say goodbye, call end_call "
    "without speaking. Never repeat a summary you already gave."
)

# Flow nodes (004) end the call through their own routing (a transition to an End node, or an
# end_call tool on the node); the End node says the goodbye, written for the call unless the
# builder wrote a fixed one (flow/runtime.py).
FLOW_ENDING_INSTRUCTION = (
    "When the conversation is over, end the call with the step your instructions give for it (a "
    "transition that ends the call, or end_call). In that reply confirm in one short sentence what "
    "was agreed or what happens next (for example when you will call back), without saying "
    "goodbye: the goodbye is said as the call ends. If you have no step that ends the call, say "
    "goodbye in your reply. "
    + CALLER_HAS_TO_GO
    + " Never promise something you cannot do. Never repeat a summary you already gave."
)

# 011: every agent also has the built-in schedule_callback tool (flow nodes too).
CALLBACK_INSTRUCTION = (
    "If the caller asks to be called back later, ask what time suits them if they have not said, "
    "then book it with schedule_callback: the local date and time they agreed to (or in_minutes "
    "for a time like 'in an hour') and a one-sentence note of what to continue. Tell the caller "
    "the confirmed time from the result, then {close}. If the result says a callback cannot be "
    "booked, tell the caller honestly and offer what the result suggests; never promise a "
    "callback that was not booked."
)
CALLBACK_CLOSE = "say goodbye and end the call"
FLOW_CALLBACK_CLOSE = "end the call as described above"


def callback_instructions(
    variables: Mapping[str, Any], direction: str, *, flow: bool = False
) -> str:
    """The caller's current local time (to resolve "tomorrow at 5"), the callback rule and, on a
    callback call itself, why the agent is calling."""
    now = local_now(variables)
    zone = str(variables.get("timezone") or "UTC")
    parts = [
        f"It is now {now:%A} {now.day} {now:%B %Y}, {clock(now)} for the caller "
        f"({zone}, {now.isoformat(timespec='minutes')}).",
        CALLBACK_INSTRUCTION.format(close=FLOW_CALLBACK_CLOSE if flow else CALLBACK_CLOSE),
    ]
    if direction == "outbound" and CALLBACK_NOTE in variables:
        note = str(variables.get(CALLBACK_NOTE) or "").strip()
        if note and note[-1] not in ".!?":
            note += "."
        parts.append(
            "This call is the callback you promised"
            + (f": {note}" if note else ".")
            + " Say you are calling back as agreed and continue from there."
        )
    return " ".join(parts)


def builtin_instructions(runtime: RuntimeConfig, *, flow: bool = False) -> str:
    """The callback rule (with the caller's local time) and, when the claim offers more than one
    language, the set_language rule: the same for single-prompt agents and every flow node."""
    callback = callback_instructions(runtime.variables, runtime.direction, flow=flow)
    options = runtime.language_options
    switching = set_language_instruction(options) if len(options) > 1 else ""
    return "\n\n".join(p for p in (callback, switching) if p)


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
    # 012: the agent's configured language (``language`` is the call's current one), the label
    # of the language replies must use when it is not the agent's, and the label to say a fixed
    # greeting in when the call starts in the caller's saved language.
    agent_language: str | None = None
    reply_language: str | None = None
    greeting_language: str | None = None

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


def auto_stt(rules: Mapping[str, SttAuto], provider: str, language: str) -> str:
    """The model speech recognition Auto runs, from the claim's table (the API's rule, FR-045)."""
    rule = rules.get(provider)
    model = rule.resolve(language) if rule is not None else None
    if model is None:
        raise UnsupportedLanguage(provider, language)
    return model


def resolve_stt(
    config: Mapping[str, Any],
    registry: AdapterRegistry,
    stt_auto_rules: Mapping[str, SttAuto],
    *,
    language: str,
    resolved_model: str | None = None,
) -> tuple[VendorSpec, bool]:
    """STT spec with Auto (``model: null``) resolved for the language (FR-045)."""
    raw = _section(config, "stt")
    provider = registry.normalize_provider("stt", str(raw.get("provider") or ""))
    model = raw.get("model")
    auto = model in (None, "")
    if auto:
        model = resolved_model or auto_stt(stt_auto_rules, provider, language)
    spec = registry.check(VendorSpec("stt", provider, str(model), {"language": language}))
    return spec, auto


def resolve_llm(config: Mapping[str, Any], registry: AdapterRegistry) -> VendorSpec:
    raw = _section(config, "llm")
    options: dict[str, Any] = {}
    if raw.get("temperature") is not None:
        options["temperature"] = float(raw["temperature"])
    provider, model = str(raw.get("provider") or ""), raw.get("model")
    if not model:
        raise UnsupportedVendor("llm", provider)
    return registry.check(VendorSpec("llm", provider, str(model), options))


def resolve_tts(
    config: Mapping[str, Any], registry: AdapterRegistry, *, language: str
) -> VendorSpec:
    raw = _section(config, "tts")
    provider = str(raw.get("provider") or "")
    entry = registry.entry("tts", provider)
    model = raw.get("model") or entry.default_model
    options: dict[str, Any] = {"language": language}
    for key in ("voice_id", "speed", "expressiveness", "volume"):
        if raw.get(key) is not None:
            options[key] = raw[key]
    return registry.check(VendorSpec("tts", provider, model, options))


def tts_gain_for(tts: VendorSpec, registry: AdapterRegistry) -> float:
    """Output gain the worker applies when the vendor has no native volume control."""
    volume = float(tts.options.get("volume", 1.0))
    if registry.native_volume(tts):
        return 1.0
    return volume


# Agent


TtsTextHook = Callable[[str], None]


async def pronounce(
    text: AsyncIterable[str], transform: PronunciationTransform, on_text: TtsTextHook | None
) -> AsyncIterator[str]:
    """Pronunciation transform for the TTS node; ``on_text`` sees what is sent to TTS (R7)."""
    async for chunk in transform.stream(text):
        if on_text is not None:
            on_text(chunk)
        yield chunk


class FillerSource(Protocol):
    """005's ``FillerPolicy``: lookup tool names and the line to say when one is called, and the
    end_call tools whose ``goodbye`` argument replaces that line."""

    reply_spoke: bool
    end_call_names: frozenset[str]

    def text_for(self, names: Sequence[str]) -> str | None: ...


def goodbye_argument(calls: Sequence[Any], policy: FillerSource) -> str | None:
    """The goodbye the model wrote into an end_call that came without spoken words."""
    for call in calls:
        if str(getattr(call, "name", "")) not in policy.end_call_names:
            continue
        try:
            args = json.loads(getattr(call, "arguments", "") or "{}")
        except ValueError:
            continue
        said = str(args.get("goodbye") or "").strip() if isinstance(args, dict) else ""
        if said:
            return said
    return None


async def with_fillers(
    stream: AsyncIterable[Any], policy: FillerSource | None
) -> AsyncIterator[Any]:
    """Pass the LLM stream through; when the first tool call of a reply arrives before any text
    and the tool is a lookup (HTTP or knowledge search), say its filler line at once so the
    caller is not left in silence while the tool runs. ``policy.reply_spoke`` tells the tools
    whether this reply already said something (so they skip their own waiting line)."""
    if policy is None:
        async for chunk in stream:
            yield chunk
        return
    policy.reply_spoke = False
    spoke = False
    async for chunk in stream:
        if isinstance(chunk, str):
            spoke = spoke or bool(chunk.strip())
        else:
            delta = getattr(chunk, "delta", None)
            if delta is not None:
                spoke = spoke or bool((getattr(delta, "content", None) or "").strip())
                calls = getattr(delta, "tool_calls", None) or []
                if calls and not spoke:
                    filler = goodbye_argument(calls, policy) or policy.text_for(
                        [str(getattr(c, "name", "")) for c in calls]
                    )
                    if filler:
                        yield filler + " "
                        spoke = True
                if calls:
                    policy.reply_spoke = spoke
        yield chunk


def make_agent_class() -> type[Any]:
    """The LiveKit agent of single-prompt calls and the base of flow node agents. Built lazily so
    pure tests never import LiveKit."""
    from livekit.agents import Agent

    class CallwrightAgent(Agent):
        """Applies pronunciation and output gain in the TTS node; transcript keeps LLM text."""

        def __init__(
            self,
            plan: SessionPlan,
            *,
            tools: Sequence[Any] = (),
            on_tts_text: TtsTextHook | None = None,
            extra_instructions: str = "",
            filler_policy: FillerSource | None = None,
            ending_instruction: str = ENDING_INSTRUCTION,
            **kwargs: Any,
        ) -> None:
            instructions = "\n\n".join(
                p
                for p in (
                    plan.instructions,
                    VOICE_STYLE_INSTRUCTION,
                    ending_instruction,
                    extra_instructions,
                )
                if p
            )
            instructions = with_reply_language(instructions, plan.reply_language)
            if plan.reply_language is None and language_base(plan.language) == "multi":
                instructions = f"{instructions}\n\n{FOLLOW_CALLER_LANGUAGE}".strip()
            super().__init__(instructions=instructions, tools=list(tools), **kwargs)
            self.plan = plan
            self._on_tts_text = on_tts_text
            self._fillers = filler_policy

        async def llm_node(
            self, chat_ctx: Any, tools: list[Any], model_settings: Any
        ) -> AsyncIterator[Any]:
            stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
            async for chunk in with_fillers(stream, self._fillers):
                yield chunk

        async def set_reply_language(self, label: str) -> None:
            """012 set_language: reply in ``label`` from now on."""
            await self.update_instructions(with_reply_language(str(self.instructions), label))

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
