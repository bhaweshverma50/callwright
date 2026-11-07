"""T038, T063, T116: session assembly from a frozen version for every launch vendor combination."""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.unit.conftest import call_tools, make_runtime
from worker.adapters.registry import AdapterRegistry, UnsupportedVendor
from worker.agent import (
    CALLBACK_CLOSE,
    CALLBACK_INSTRUCTION,
    ENDING_INSTRUCTION,
    VOICE_STYLE_INSTRUCTION,
    callback_instructions,
    pronounce,
)
from worker.audio import PronunciationEntry, PronunciationTransform
from worker.flow import FlowRuntimeUnavailable
from worker.flow.runtime import CallwrightFlowRunner
from worker.pipeline import (
    build_agent,
    build_components,
    build_session,
    plan_session,
    vendor_error_diagnostic,
)

STT = [
    {"provider": "deepgram", "model": None},
    {"provider": "deepgram", "model": "flux-general-en"},
    {"provider": "assemblyai", "model": None},
    {"provider": "sarvam", "model": "saaras:v3"},
]
LLM = [
    {"provider": "azure_openai", "model": "gpt-5.1"},
    {"provider": "openai", "model": "gpt-5-mini"},
]
TTS = [
    {"provider": "elevenlabs", "model": "eleven_turbo_v2_5"},
    {"provider": "cartesia", "model": "sonic-3"},
    {"provider": "fishaudio", "model": "s1"},
]
NC = [{"provider": "sanas", "model": "st"}, {"provider": "ai_coustics", "model": "standard"}, None]
COMBOS = list(itertools.product(STT, LLM, TTS, NC))
CREDS = {
    p: {"api_key": "test", "endpoint": "https://example.openai.azure.com"}
    for p in (
        "deepgram",
        "assemblyai",
        "sarvam",
        "openai",
        "azure_openai",
        "elevenlabs",
        "cartesia",
        "fishaudio",
        "sanas",
        "ai_coustics",
    )
}
PLUGIN_MODULE = {
    "deepgram": "livekit.plugins.deepgram",
    "assemblyai": "livekit.plugins.assemblyai",
    "sarvam": "livekit.plugins.sarvam",
    "openai": "livekit.plugins.openai",
    "azure_openai": "livekit.plugins.openai",
    "elevenlabs": "livekit.plugins.elevenlabs",
    "cartesia": "livekit.plugins.cartesia",
    "fishaudio": "livekit.plugins.fishaudio",
}


def combo_id(c: tuple[Any, ...]) -> str:
    stt, llm, tts, nc = c
    return "-".join(
        [
            f"{stt['provider']}:{stt['model'] or 'auto'}",
            llm["provider"],
            tts["provider"],
            nc["provider"] if nc else "nc_off",
        ]
    )


@pytest.mark.parametrize("combo", COMBOS, ids=[combo_id(c) for c in COMBOS])
async def test_pipeline_assembles_for_every_vendor_combination(
    combo: tuple[Any, ...], no_llm_prewarm: None
) -> None:
    stt, llm, tts, nc = combo
    language = "hi" if stt["provider"] == "sarvam" else "en-US"
    config = {"language": language, "stt": stt, "llm": llm, "tts": tts, "noise_cancellation": nc}
    registry = AdapterRegistry()
    plan = plan_session(make_runtime(config), registry)
    expected_turn = (
        "stt"
        if stt["provider"] == "assemblyai" or stt["model"] == "flux-general-en"
        else "semantic"
    )
    assert plan.turn_detection == expected_turn
    assert plan.stt.model is not None  # Auto resolved
    assert plan.nc.provider == (nc["provider"] if nc else "none")

    components = build_components(plan, registry, CREDS)
    for kind in ("stt", "llm", "tts"):
        provider = plan.spec(kind).provider
        assert type(components.get(kind)).__module__.startswith(PLUGIN_MODULE[provider])
    assert (components.nc is None) == (nc is None)

    session = build_session(plan, components, vad=None)
    assert session.stt is components.stt
    assert session.llm is components.llm
    assert session.tts is components.tts


def test_plan_renders_prompt_and_greeting_with_variables() -> None:
    plan = plan_session(
        make_runtime(variables={"customer_name": "Priya", "company_name": "Northwind"}),
        AdapterRegistry(),
    )
    assert plan.instructions.startswith("You are the receptionist at Northwind.")
    assert plan.greeting == "Hi Priya, thanks for calling Northwind. How can I help?"
    assert plan.start_speaker == "agent" and not plan.generated_greeting


def test_empty_greeting_is_generated_and_user_first_has_none() -> None:
    gen = plan_session(make_runtime({"begin_message": ""}), AdapterRegistry())
    assert gen.greeting is None and gen.generated_greeting
    user = plan_session(make_runtime({"start_speaker": "user"}), AdapterRegistry())
    assert user.start_speaker == "user" and not user.generated_greeting


def test_auto_stt_uses_claim_resolved_model() -> None:
    plan = plan_session(make_runtime(stt_resolved_model="nova-2"), AdapterRegistry())
    assert plan.stt_auto and plan.stt.model == "nova-2"


def test_noise_cancellation_from_the_claim_and_off() -> None:
    assert plan_session(make_runtime(), AdapterRegistry()).nc.key == "nc/sanas/vi"
    off = plan_session(make_runtime({"noise_cancellation": None}), AdapterRegistry())
    assert off.nc.key == "nc/none/none"


def test_unsupported_vendor_fails_planning() -> None:
    with pytest.raises(UnsupportedVendor) as exc:
        plan_session(make_runtime({"tts": {"provider": "sarvam"}}), AdapterRegistry())
    assert exc.value.diagnostic == "unsupported_vendor:tts/sarvam"


def test_tts_gain_only_without_native_volume() -> None:
    eleven = plan_session(make_runtime({"tts": {"volume": 1.5}}), AdapterRegistry())
    assert eleven.tts_gain == 1.5
    fish = plan_session(
        make_runtime({"tts": {"provider": "fishaudio", "model": "s1", "volume": 1.5}}),
        AdapterRegistry(),
    )
    assert fish.tts_gain == 1.0
    sonic2 = plan_session(
        make_runtime({"tts": {"provider": "cartesia", "model": "sonic-2", "volume": 0.5}}),
        AdapterRegistry(),
    )
    assert sonic2.tts_gain == 0.5


def test_flow_agent_without_a_compiled_flow_fails_with_a_diagnostic() -> None:
    runtime = make_runtime({"type": "flow"})
    with pytest.raises(FlowRuntimeUnavailable) as exc:
        plan_session(runtime, AdapterRegistry(), CallwrightFlowRunner())
    assert exc.value.diagnostic == "flow_not_compiled"


def test_single_prompt_agent_carries_plan_and_instructions() -> None:
    runtime = make_runtime()
    plan = plan_session(runtime, AdapterRegistry())
    agent = build_agent(plan, runtime, None, call_tools(runtime))  # type: ignore[arg-type]
    assert agent.plan is plan
    callback = callback_instructions(runtime.variables, runtime.direction)
    assert agent.instructions == (
        f"{plan.instructions}\n\n{VOICE_STYLE_INSTRUCTION}\n\n{ENDING_INSTRUCTION}\n\n{callback}"
    )
    assert CALLBACK_INSTRUCTION.format(close=CALLBACK_CLOSE) in callback
    assert callback.startswith("It is now ")


def test_callback_instructions_give_local_time_and_callback_reason() -> None:
    variables = {"timezone": "Asia/Kolkata", "current_datetime": "2026-11-03T14:05+05:30"}
    text = callback_instructions(variables, "inbound")
    assert "(Asia/Kolkata, " in text and "+05:30)" in text
    assert "callback you promised" not in text
    callback = callback_instructions({**variables, "callback_note": "Finish rebooking"}, "outbound")
    assert "This call is the callback you promised: Finish rebooking." in callback


async def test_pronounce_meters_text_sent_to_tts() -> None:
    async def source() -> AsyncIterator[str]:
        for chunk in ["We run S", "QL daily."]:
            yield chunk

    sent: list[str] = []
    transform = PronunciationTransform([PronunciationEntry("SQL", "sequel")])
    out = [c async for c in pronounce(source(), transform, sent.append)]
    assert "".join(out) == "We run sequel daily."
    assert sum(len(s) for s in sent) == len("We run sequel daily.")


async def test_vendor_error_diagnostic(no_llm_prewarm: None) -> None:
    registry = AdapterRegistry()
    plan = plan_session(make_runtime(), registry)
    components = build_components(plan, registry, CREDS)
    assert vendor_error_diagnostic(components.stt, plan) == "vendor_error:stt/deepgram"
    assert vendor_error_diagnostic(components.llm, plan) == "vendor_error:llm/azure_openai"
    assert vendor_error_diagnostic(components.tts, plan) == "vendor_error:tts/elevenlabs"
    assert vendor_error_diagnostic(object(), plan) == "vendor_error:runtime/unknown"


async def test_voicemail_tool_is_added_with_its_instruction() -> None:
    from worker.call_behavior import VOICEMAIL_INSTRUCTION, VOICEMAIL_TOOL_NAME
    from worker.pipeline import voicemail_tool

    reports: list[bool] = []

    def report() -> bool:
        reports.append(True)
        return True

    runtime = make_runtime(channel="sip_outbound")
    plan = plan_session(runtime, AdapterRegistry())
    tool = voicemail_tool(report)
    agent = build_agent(
        plan,
        runtime,
        None,  # type: ignore[arg-type]
        call_tools(runtime),
        extra_tools=[tool],
        extra_instructions=VOICEMAIL_INSTRUCTION,
    )
    assert [t.info.name for t in agent.tools] == [
        "end_call",
        "schedule_callback",
        VOICEMAIL_TOOL_NAME,
    ]
    assert agent.instructions.endswith(VOICEMAIL_INSTRUCTION)
    assert await tool() == "answering machine noted"
    assert reports == [True]


def test_a_non_english_agent_tells_the_model_its_language() -> None:
    """Speech recognition and voice follow the agent's language; the model must hear it too."""
    registry = AdapterRegistry()
    stt = {"provider": "sarvam", "model": None}
    hindi = make_runtime(
        {"language": "hi", "stt": stt, "begin_message": "Namaste"},
        language_options=[
            {"code": "hi", "label": "Hindi"},
            {"code": "en-US", "label": "English (US)"},
        ],
    )
    plan = plan_session(hindi, registry)
    assert plan.reply_language == "Hindi"
    assert plan.greeting_language is None, "the greeting is already in the agent's language"
    assert (
        plan_session(make_runtime({"language": "hi", "stt": stt}), registry).reply_language == "hi"
    )
    assert plan_session(make_runtime({"language": "en-US"}), registry).reply_language is None


def test_a_multilingual_agent_follows_the_caller_language() -> None:
    from worker.agent import make_agent_class
    from worker.language import FOLLOW_CALLER_LANGUAGE

    plan = plan_session(make_runtime({"language": "multi"}), AdapterRegistry())
    assert plan.reply_language is None, "no 'reply only in Multilingual'"
    agent = make_agent_class()(plan)
    assert agent.instructions.endswith(FOLLOW_CALLER_LANGUAGE)


def test_elevenlabs_gets_no_language_code_for_multi() -> None:
    from worker.adapters.registry import VendorSpec
    from worker.adapters.tts import elevenlabs

    tts = elevenlabs.build(
        VendorSpec("tts", "elevenlabs", "eleven_flash_v2_5", {"language": "multi"}),
        {"api_key": "k"},
    )
    assert not isinstance(tts._opts.language, str), "no language code sent"
