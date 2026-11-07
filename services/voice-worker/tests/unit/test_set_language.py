"""Caller language (012): the set_language tool (schema, overrides, instructions, report),
starting a call in the caller's saved language, and the translated greeting."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.unit.conftest import call_tools, make_runtime
from tests.unit.tool_support import Backend
from worker.adapters.registry import AdapterRegistry
from worker.control import RuntimeCallControl
from worker.internal_api import InternalApiClient
from worker.language import (
    reply_language_instruction,
    set_language_instruction,
    translate_greeting,
    with_reply_language,
)
from worker.metrics import EventRecorder
from worker.pipeline import OverrideManager, build_agent, plan_session
from worker.tools.registry import build_call_tools, function_schema

OPTIONS = [
    {
        "code": "en-US",
        "label": "English (US)",
        "stt_model": "nova-3",
        "tts_model": "eleven_flash_v2_5",
    },
    {"code": "hi", "label": "Hindi", "stt_model": "nova-2", "tts_model": "eleven_flash_v2_5"},
    {"code": "es", "label": "Spanish", "stt_model": "nova-2", "tts_model": "eleven_flash_v2_5"},
]


def setup(
    *,
    channel: str = "sip_inbound",
    simulation: bool = False,
    options: list[dict[str, Any]] | None = None,
    caller_language: str | None = None,
    overrides: bool = True,
) -> Any:
    runtime = make_runtime(
        channel=channel,
        language_options=OPTIONS if options is None else options,
        caller_language=caller_language,
    )
    if simulation:
        runtime = runtime.model_copy(update={"simulation": True})
    plan = plan_session(runtime, AdapterRegistry())
    recorder = EventRecorder()
    manager = (
        OverrideManager(plan, AdapterRegistry(), runtime.controls, runtime.stt_auto_rules)
        if overrides
        else None
    )
    staged: list[bool] = []
    control = RuntimeCallControl(
        "call_test",
        recorder,
        Backend(),
        overrides=manager,
        on_overrides_staged=lambda: staged.append(True),
    )
    seen: list[httpx.Request] = []

    def api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"recorded": True, "stored": True, "reason": "saved"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(api))
    tools = build_call_tools(
        runtime,
        control,
        api=InternalApiClient("http://api.test/v1/internal", "svc", http=client),
    )
    return SimpleNamespace(
        runtime=runtime,
        plan=plan,
        recorder=recorder,
        manager=manager,
        control=control,
        tools=tools,
        seen=seen,
        staged=staged,
    )


async def settle(tools: Any) -> None:
    executor = tools.executors["set_language"]
    if executor.reports:
        await asyncio.gather(*executor.reports)


def test_schema_lists_the_offered_codes() -> None:
    h = setup()
    spec = h.tools.by_name["set_language"]
    schema = function_schema(spec)
    language = schema["parameters"]["properties"]["language"]
    assert language["enum"] == ["en-US", "hi", "es"]
    assert "hi = Hindi" in language["description"]
    assert schema["parameters"]["required"] == ["language"]
    assert "set_language" not in setup(options=[OPTIONS[0]]).tools.by_name
    assert "set_language" not in setup(options=[]).tools.by_name


async def test_switch_stages_speech_voice_and_reply_language_and_reports_it() -> None:
    h = setup()
    instructions: list[str] = []

    async def relabel(label: str) -> None:
        instructions.append(label)

    h.tools.ctx.set_reply_language = relabel
    payload = json.loads(await h.tools.dispatch("set_language", {"language": "hi"}))
    assert (
        payload["switched"]
        and payload["label"] == "Hindi"
        and "only in Hindi" in payload["message"]
    )
    assert instructions == ["Hindi"] and h.staged == [True]
    swap = h.manager.apply_pending()
    assert swap is not None and set(swap.kinds) == {"stt", "tts"}
    stt = swap.specs["stt"]
    assert (stt.model, stt.options["language"]) == ("nova-2", "hi")
    assert swap.specs["tts"].options["language"] == "hi"
    plan = h.manager.plan_for_current()
    assert plan.language == "hi" and plan.reply_language == "Hindi"
    agent = build_agent(plan, h.runtime, None, call_tools(h.runtime))  # type: ignore[arg-type]
    assert agent.instructions.endswith(reply_language_instruction("Hindi"))

    await settle(h.tools)
    assert [str(r.url) for r in h.seen] == ["http://api.test/v1/internal/calls/call_test/language"]
    assert json.loads(h.seen[0].content)["language"] == "hi"
    assert h.seen[0].headers["authorization"] == "Bearer svc"
    events = h.recorder.drain()
    system = [
        e["item"]
        for e in events
        if e["type"] == "transcript_item" and e["item"]["type"] == "system"
    ]
    assert system[-1]["event"] == "language_switched" and system[-1]["detail"] == "Hindi (hi)"
    calls = [e for e in events if e["type"] == "tool_call"]
    assert calls[-1]["name"] == "set_language" and not calls[-1]["is_error"]

    # The same language again changes nothing; switching back restores the agent's models.
    again = json.loads(await h.tools.dispatch("set_language", {"language": "hi"}))
    assert again["switched"] is False and not h.manager.pending
    await h.tools.dispatch("set_language", {"language": "en-US"})
    back = h.manager.apply_pending()
    assert back is not None and back.specs["stt"].model == "nova-3"
    assert h.manager.plan_for_current().reply_language == "English (US)"
    await settle(h.tools)
    await h.tools.aclose()


async def test_unknown_language_is_refused_and_simulations_never_report() -> None:
    h = setup(simulation=True, overrides=False)
    bad = json.loads(await h.tools.dispatch("set_language", {"language": "fr"}))
    assert bad["error"] == "invalid_arguments"  # not in the enum
    ok = json.loads(await h.tools.dispatch("set_language", {"language": "es"}))
    assert ok["switched"]
    await settle(h.tools)
    assert h.seen == []


def test_call_starts_in_the_saved_language() -> None:
    runtime = make_runtime(channel="sip_inbound", language_options=OPTIONS, caller_language="hi")
    plan = plan_session(runtime, AdapterRegistry())
    assert plan.language == "hi" and plan.agent_language == "en-US"
    assert (plan.stt.model, plan.stt.options["language"]) == ("nova-2", "hi")
    assert plan.tts.options["language"] == "hi"
    assert plan.reply_language == "Hindi" and plan.greeting_language == "Hindi"
    agent = build_agent(plan, runtime, None, call_tools(runtime))  # type: ignore[arg-type]
    assert reply_language_instruction("Hindi") in agent.instructions
    assert set_language_instruction(runtime.language_options) in agent.instructions

    for code in ("en-US", "fr", None):
        same = plan_session(
            make_runtime(language_options=OPTIONS, caller_language=code), AdapterRegistry()
        )
        assert same.language == "en-US" and same.reply_language is None
        assert same.greeting_language is None
    nothing = make_runtime()
    agent = build_agent(
        plan_session(nothing, AdapterRegistry()),
        nothing,
        None,  # type: ignore[arg-type]
        call_tools(nothing),
    )
    assert "set_language" not in agent.instructions and "Language rule" not in agent.instructions


def test_reply_language_line_is_replaced_not_stacked() -> None:
    text = with_reply_language("Be kind.", "Hindi")
    text = with_reply_language(text, "Spanish")
    assert text == f"Be kind.\n\n{reply_language_instruction('Spanish')}"
    assert with_reply_language(text, None) == "Be kind."


class FakeLLM:
    def __init__(self, parts: list[str], *, delay: float = 0.0) -> None:
        self.parts = parts
        self.delay = delay
        self.seen: list[Any] = []

    def chat(self, *, chat_ctx: Any) -> Any:
        self.seen.append(chat_ctx)
        llm = self

        class Stream:
            async def __aenter__(self) -> AsyncIterator[Any]:
                async def chunks() -> AsyncIterator[Any]:
                    await asyncio.sleep(llm.delay)
                    for part in llm.parts:
                        yield SimpleNamespace(delta=SimpleNamespace(content=part), usage=None)
                    yield SimpleNamespace(
                        delta=None, usage=SimpleNamespace(prompt_tokens=40, completion_tokens=12)
                    )

                return chunks()

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return Stream()


async def test_greeting_translation_and_its_timeout() -> None:
    usage: list[tuple[int, int]] = []
    llm = FakeLLM(["Namaste, ", "Acme Bank mein call karne ke liye dhanyavaad."])
    text = await translate_greeting(
        llm,
        "Hi, thanks for calling Acme Bank.",
        "Hindi",
        on_usage=lambda i, o: usage.append((i, o)),
    )
    assert text == "Namaste, Acme Bank mein call karne ke liye dhanyavaad."
    assert usage == [(40, 12)]
    system = llm.seen[0].items[0]
    assert "into Hindi" in system.text_content

    with pytest.raises(TimeoutError):
        await translate_greeting(FakeLLM(["late"], delay=1.0), "Hi", "Hindi", timeout_s=0.05)
    with pytest.raises(ValueError):
        await translate_greeting(FakeLLM([" "]), "Hi", "Hindi")


class GreetingSession:
    def __init__(self) -> None:
        self.said: list[tuple[str, bool, bool]] = []
        self.generated: list[str] = []

    def say(self, text: str, *, allow_interruptions: bool = True, audio: Any = None) -> None:
        self.said.append((text, allow_interruptions, audio is not None))

    def generate_reply(self, *, instructions: str, allow_interruptions: bool = True) -> None:
        self.generated.append(instructions)


class FakeTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> Any:
        self.texts.append(text)

        class Stream:
            async def __aenter__(self) -> AsyncIterator[Any]:
                async def frames() -> AsyncIterator[Any]:
                    yield SimpleNamespace(frame="f1")

                return frames()

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return Stream()


async def greet(translation: str | Exception) -> tuple[GreetingSession, FakeTTS, Any]:
    from tests.unit.test_live_call import live_call
    from worker.pipeline import SessionComponents

    call, _, _ = live_call()
    runtime = make_runtime(channel="sip_inbound", language_options=OPTIONS, caller_language="hi")
    call.runtime = runtime
    call.plan = plan_session(runtime, AdapterRegistry())
    tts = FakeTTS()
    call.components = SessionComponents(stt=None, llm=None, tts=tts, nc=None)

    async def translate(plan: Any, greeting: str, label: str) -> str:
        assert label == "Hindi" and greeting.startswith("Hi there")
        if isinstance(translation, Exception):
            raise translation
        return translation

    call._translate_greeting = translate  # type: ignore[method-assign]
    session = GreetingSession()
    call.session = session
    task = call._presynthesize_greeting(call.plan)
    await call._connected(call.plan, task)
    for timer in (call.inactivity, call.duration):
        if timer is not None:
            timer.stop()
    return session, tts, call


async def test_saved_language_greeting_is_translated_and_presynthesised() -> None:
    session, tts, _ = await greet("Namaste, Acme Bank mein aapka swagat hai.")
    assert session.said == [("Namaste, Acme Bank mein aapka swagat hai.", False, True)]
    assert tts.texts == ["Namaste, Acme Bank mein aapka swagat hai."] and session.generated == []


async def test_greeting_falls_back_to_the_model_when_translation_fails() -> None:
    session, tts, call = await greet(TimeoutError())
    assert session.said == [] and tts.texts == []
    assert len(session.generated) == 1
    assert "in Hindi" in session.generated[0] and call.plan.greeting in session.generated[0]
