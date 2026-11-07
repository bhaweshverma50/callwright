"""Flow agents get the built-ins single-prompt agents have (011 callbacks, 012 caller language),
with ending rules that fit a flow's own routing; End nodes without a line of their own say a
goodbye written for the call; a caller who is still talking is not hung up on."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from callwright_contract.values import STOCK_GOODBYE

from tests.flow_support import (
    FlowScript,
    RecordingControl,
    Rule,
    compiled_config,
    run_flow_call,
)
from tests.harness.runner import build_runtime
from worker.adapters.registry import AdapterRegistry
from worker.agent import (
    CALLER_HAS_TO_GO,
    ENDING_INSTRUCTION,
    FLOW_CALLBACK_CLOSE,
    FLOW_ENDING_INSTRUCTION,
)
from worker.flow import FlowComponents
from worker.flow import runtime as flow_runtime
from worker.flow.nodes.end import generates
from worker.flow.runtime import CallwrightFlowRunner
from worker.pipeline import build_agent, plan_session
from worker.tools.registry import build_call_tools

pytestmark = pytest.mark.usefixtures("no_llm_prewarm")

OPTIONS = [
    {
        "code": "en-US",
        "label": "English (US)",
        "stt_model": "nova-3",
        "tts_model": "eleven_multilingual_v2",
    },
    {"code": "hi", "label": "Hindi", "stt_model": "nova-2", "tts_model": "eleven_multilingual_v2"},
]
WRAP_UP = Rule("that's all", tool="route_to_wrap_up")


def greeting_end(message: str | None = None) -> dict[str, Any]:
    config = copy.deepcopy(compiled_config("greeting_end"))
    if message is not None:
        config["flow"]["compiled"]["nodes"]["n_end00000"]["end"]["message"] = message
    return config


def tool_names(agent: Any) -> set[str]:
    return {str(getattr(t, "id", None) or getattr(t, "name", "")) for t in agent.tools}


def entry_agent(**runtime: Any) -> Any:
    """The flow's entry agent as a live call builds it (``pipeline.build_agent``)."""
    rt = build_runtime(greeting_end(), {"channel": "sip_inbound", **runtime})
    flows = CallwrightFlowRunner()
    plan = plan_session(rt, AdapterRegistry(), flows)
    control = RecordingControl()
    return build_agent(plan, rt, control, build_call_tools(rt, control), flows=flows)


def test_every_conversation_node_gets_callback_and_language_tools_and_rules() -> None:
    agent = entry_agent(language_options=OPTIONS)
    assert agent.node_id == "n_greet000"
    names = tool_names(agent)
    assert {"schedule_callback", "set_language", "route_to_wrap_up"} <= names
    assert "end_call" not in names  # a flow ends through its own routing
    text = agent.instructions
    assert FLOW_ENDING_INSTRUCTION in text and ENDING_INSTRUCTION not in text
    assert "It is now " in text and FLOW_CALLBACK_CLOSE in text
    assert "call set_language with its code" in text and "Hindi (hi)" in text


def test_without_language_options_flow_nodes_get_no_set_language() -> None:
    agent = entry_agent()
    names = tool_names(agent)
    assert "schedule_callback" in names and "set_language" not in names
    assert "set_language" not in agent.instructions


def test_ending_rules_ask_before_hanging_up_on_a_busy_caller() -> None:
    for rule in (ENDING_INSTRUCTION, FLOW_ENDING_INSTRUCTION):
        assert CALLER_HAS_TO_GO in rule
    assert "another call" in CALLER_HAS_TO_GO and "schedule_callback first" in CALLER_HAS_TO_GO
    assert "ask in one short question whether they would like a call back" in CALLER_HAS_TO_GO
    assert "call end_call in that same reply" not in FLOW_ENDING_INSTRUCTION


def test_end_node_generates_only_without_a_line_of_its_own() -> None:
    assert generates({"end": {"message": ""}})
    assert generates({"end": {"message": f"  {STOCK_GOODBYE} "}})
    assert not generates({"end": {"message": "Thanks for calling Harbour Clinic. Bye!"}})


async def test_stock_end_message_becomes_a_goodbye_written_for_the_call() -> None:
    script = FlowScript(rules=[WRAP_UP], goodbye="We'll call you back in five minutes. Bye!")
    result = await run_flow_call(greeting_end(), script, ["Okay, that's all for now"])
    assert result.control.disconnect_reason == "agent_hangup"
    assert "We'll call you back in five minutes. Bye!" in result.replies
    assert STOCK_GOODBYE not in result.replies
    (request,) = result.llm.goodbyes
    assert "Okay, that's all for now" in request.items[-1].text_content


async def test_empty_end_message_also_generates() -> None:
    script = FlowScript(rules=[WRAP_UP], goodbye="Take care, goodbye!")
    result = await run_flow_call(greeting_end(""), script, ["that's all"])
    assert "Take care, goodbye!" in result.replies
    assert result.control.disconnect_reason == "agent_hangup"


async def test_custom_end_message_is_spoken_verbatim() -> None:
    script = FlowScript(rules=[WRAP_UP])
    result = await run_flow_call(
        greeting_end("Thanks for calling Harbour Clinic. Bye!"), script, ["that's all"]
    )
    assert "Thanks for calling Harbour Clinic. Bye!" in result.replies
    assert result.llm.goodbyes == []


async def test_failed_goodbye_falls_back_to_the_stock_line() -> None:
    script = FlowScript(rules=[WRAP_UP], goodbye=None)
    result = await run_flow_call(greeting_end(), script, ["that's all"])
    assert STOCK_GOODBYE in result.replies
    assert result.control.disconnect_reason == "agent_hangup"


async def test_slow_goodbye_falls_back_in_bounded_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flow_runtime, "GOODBYE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(flow_runtime, "GOODBYE_AFTER_PLAYOUT_S", 0.1)
    script = FlowScript(rules=[WRAP_UP], goodbye="Too late.", goodbye_delay_s=5.0)
    result = await run_flow_call(greeting_end(""), script, ["that's all"])
    assert STOCK_GOODBYE in result.replies and "Too late." not in result.replies


async def test_no_second_goodbye_after_the_reply_said_one() -> None:
    rt = build_runtime(greeting_end(), {})
    plan = plan_session(rt, AdapterRegistry(), CallwrightFlowRunner())
    control = RecordingControl()
    call = flow_runtime.FlowCall(rt, control, plan, base_tools=build_call_tools(rt, control))
    call.reply_text = "Sure, I'll call you back in five minutes. Bye now!"
    assert await call.closing_line(STOCK_GOODBYE) == ""


class TalkingCaller(RecordingControl):
    """The caller keeps talking after the turn that the model answered with a goodbye."""

    def __init__(self) -> None:
        super().__init__()
        self.asked = 0

    async def caller_quiet(self) -> bool:
        self.asked += 1
        return False


async def test_caller_still_talking_is_not_hung_up_on() -> None:
    control = TalkingCaller()
    script = FlowScript(rules=[Rule("getting a call", tool="route_to_wrap_up")])
    result = await run_flow_call(greeting_end(), script, ["I'm getting a call."], control=control)
    assert control.asked == 1
    assert control.disconnect_reason is None
    assert [t["to_node_id"] for t in control.transitions] == ["n_greet000"]
    assert not any("Goodbye" in r for r in result.replies)  # nothing was said over them


def flow_call(**runtime: Any) -> flow_runtime.FlowCall:
    rt = build_runtime(greeting_end(), {"channel": "sip_inbound", **runtime})
    plan = plan_session(rt, AdapterRegistry(), CallwrightFlowRunner())
    control = RecordingControl()
    return flow_runtime.FlowCall(rt, control, plan, base_tools=build_call_tools(rt, control))


async def test_switched_language_carries_to_nodes_built_later() -> None:
    call = flow_call(language_options=OPTIONS)
    agent = call.agent_for("n_greet000", initial=True)
    await agent.set_reply_language("Hindi")
    assert call.reply_language == "Hindi" and "reply only in Hindi" in agent.instructions
    later = call.agent_for("n_greet000")
    assert "reply only in Hindi" in later.instructions


def test_turn_boundary_swap_rebuilds_the_current_node_not_the_flow() -> None:
    from dataclasses import replace

    call = flow_call(language_options=OPTIONS)
    agent = call.agent_for("n_greet000", initial=True)
    call.current_agent = agent
    plan = replace(call.plan, language="hi", reply_language="Hindi")
    stt, tts = object(), object()
    rebuilt = call.rebuild(plan, {"stt": stt, "llm": None, "tts": tts})
    assert rebuilt is not agent and rebuilt.node_id == "n_greet000"
    assert rebuilt.initial  # rebuilt in place: says nothing on entry
    assert "reply only in Hindi" in rebuilt.instructions
    assert call.default_components == {"stt": stt, "tts": tts}
    assert call.agent_for("n_greet000").stt is stt  # later nodes use them too
    assert call.run.state.visited == ["n_start000"]  # the flow did not restart


def test_caller_language_wins_over_a_node_voice() -> None:
    from dataclasses import replace

    from worker.adapters.registry import VendorSpec

    built: list[VendorSpec] = []

    def build(spec: VendorSpec) -> str:
        built.append(spec)
        return f"{spec.kind}:{spec.model}"

    call = flow_call()
    call.components = FlowComponents(AdapterRegistry(), build)
    node = dict(call.run.node("n_greet000"))
    node["tts"] = {**node["tts"], "voice_id": "another-voice"}
    assert "tts" in call.node_components(node).built  # the node's own voice in the agent's language
    built.clear()
    call.plan = replace(call.plan, language="hi", reply_language="Hindi")
    assert "tts" not in call.node_components(node).built and not built


async def test_flow_node_books_a_callback_and_the_goodbye_confirms_it() -> None:
    config = greeting_end()
    config["simulation"] = True  # schedule_callback answers a mocked booking
    callback = Rule(
        "call me in five minutes",
        tool="schedule_callback",
        args={"in_minutes": 5, "note": "Finish the flight search."},
    )
    script = FlowScript(rules=[callback, WRAP_UP], goodbye="Talk in five minutes. Bye!")
    result = await run_flow_call(
        config,
        script,
        ["I'm getting a call. Can you call me in five minutes?", "that's all"],
        runtime={"channel": "sip_inbound"},
    )
    (booked,) = [t for t in result.control.tools if t.name == "schedule_callback"]
    assert not booked.is_error and '"scheduled":true' in str(booked.output)
    (request,) = result.llm.goodbyes
    assert "A callback was booked on this call for " in request.items[0].text_content
    assert "Talk in five minutes. Bye!" in result.replies
    assert result.control.disconnect_reason == "agent_hangup"
