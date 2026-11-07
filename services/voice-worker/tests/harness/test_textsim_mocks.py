"""Tool answers in simulations (008 T016, research R4, FR-013): an HTTP tool or webhook node is
answered by its mock, then (replay only) the k-th recorded output of that tool, then a
synthesized stand-in or ``no_mock_configured``; every answer is labelled with its source."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from tests.flow_support import Rule
from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    agent_script,
    deps,
    flow,
    http_tool,
    last_tool_output,
    sim_spec,
)
from tests.unit.conftest import make_runtime
from tests.unit.tool_support import Backend, make
from worker.control import RuntimeCallControl
from worker.metrics import EventRecorder
from worker.textsim import runner
from worker.textsim.mock_tools import NO_MOCK, SimulatedToolAnswers, install
from worker.tools.base import ToolSpecView
from worker.tools.registry import build_call_tools


class Synth:
    def __init__(self, reply: str = '{"slots":["10:00"]}', fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, spec: ToolSpecView, args: Mapping[str, Any]) -> str:
        self.calls.append((spec.name, dict(args)))
        if self.fail:
            raise RuntimeError("model down")
        return self.reply


def harness(tools: list[dict[str, Any]], answers: SimulatedToolAnswers) -> Any:
    h = make(tools, simulation=True)  # its HTTP client only records stray requests
    h.tools.executors.pop("http", None)
    install(h.tools, answers)
    return h


async def test_mock_wins_over_recorded_and_synthesized() -> None:
    synth = Synth()
    answers = SimulatedToolAnswers(
        replay=True, recorded=[("slots", '{"from":"recording"}')], synthesize=synth
    )
    h = harness([http_tool("slots", mock='{"from":"mock"}')], answers)
    payload = await h.tools.dispatch("slots", {"ref": "a"})
    assert json.loads(payload) == {"from": "mock"}
    assert synth.calls == [] and h.requests == []
    assert h.events()[0]["answer_source"] == "mock"
    assert answers.counts == {"mock": 1, "recorded": 0, "synthesized": 0, "error": 0}


async def test_replay_uses_kth_recorded_output_of_the_same_tool() -> None:
    recorded = [
        ("slots", '{"n":1}'),
        ("weather", '{"sky":"grey"}'),
        ("slots", '{"n":2}'),
    ]
    answers = SimulatedToolAnswers(replay=True, recorded=recorded, synthesize=Synth())
    h = harness([http_tool("slots"), http_tool("weather")], answers)
    first = await h.tools.dispatch("slots", {})
    sky = await h.tools.dispatch("weather", {})
    second = await h.tools.dispatch("slots", {})
    assert [json.loads(p) for p in (first, sky, second)] == [{"n": 1}, {"sky": "grey"}, {"n": 2}]
    assert [e["answer_source"] for e in h.events()] == ["recorded"] * 3
    assert h.requests == []


async def test_recorded_outputs_run_out_then_synthesize_with_mappings() -> None:
    synth = Synth('{"slots":["10:00"]}')
    answers = SimulatedToolAnswers(
        replay=True, recorded=[("slots", '{"slots":["09:00"]}')], synthesize=synth
    )
    mappings = [{"variable_name": "next_slot", "json_path": "slots[0]"}]
    h = harness([http_tool("slots", mappings=mappings)], answers)
    await h.tools.dispatch("slots", {"ref": "x"})
    assert h.tools.ctx.mapped_variables == {"next_slot": "09:00"}
    payload = await h.tools.dispatch("slots", {"ref": "y"})
    assert json.loads(payload) == {"slots": ["10:00"]}
    assert h.tools.ctx.mapped_variables == {"next_slot": "10:00"}
    assert synth.calls == [("slots", {"ref": "y"})]
    assert [e["answer_source"] for e in h.events()] == ["recorded", "synthesized"]
    assert answers.counts == {"mock": 0, "recorded": 1, "synthesized": 1, "error": 0}


async def test_persona_mode_never_uses_recorded_outputs() -> None:
    synth = Synth()
    answers = SimulatedToolAnswers(replay=False, recorded=[("slots", "{}")], synthesize=synth)
    h = harness([http_tool("slots")], answers)
    await h.tools.dispatch("slots", {})
    assert h.events()[0]["answer_source"] == "synthesized" and len(synth.calls) == 1


async def test_error_policy_answers_no_mock_configured() -> None:
    synth = Synth()
    answers = SimulatedToolAnswers(policy="error", synthesize=synth)
    h = harness([http_tool("slots")], answers)
    payload = await h.tools.dispatch("slots", {})
    assert json.loads(payload) == {"error": NO_MOCK}
    event = h.events()[0]
    assert event["answer_source"] == "error" and event["is_error"] is True
    assert event["error_code"] == NO_MOCK and synth.calls == []
    assert answers.counts["error"] == 1


async def test_failed_synthesis_is_an_error_answer() -> None:
    answers = SimulatedToolAnswers(synthesize=Synth(fail=True))
    h = harness([http_tool("slots")], answers)
    payload = json.loads(await h.tools.dispatch("slots", {}))
    assert payload["error"] == "synthesis_failed"
    assert h.events()[0]["answer_source"] == "error"


async def test_transcript_items_carry_the_answer_source() -> None:
    answers = SimulatedToolAnswers(synthesize=Synth())
    h = harness([http_tool("slots", mock='{"a":1}')], answers)
    await h.tools.dispatch("slots", {})
    items = [e["item"] for e in h.recorder.drain() if e["type"] == "transcript_item"]
    assert [(i["type"], i.get("answer_source")) for i in items] == [
        ("tool_call", "mock"),
        ("tool_result", "mock"),
    ]


async def test_no_http_executor_in_simulations() -> None:
    runtime = make_runtime({"tools": [http_tool("slots")]}).model_copy(update={"simulation": True})
    control = RuntimeCallControl("call_sim", EventRecorder(), Backend())
    tools = install(build_call_tools(runtime, control), SimulatedToolAnswers(synthesize=Synth()))
    assert "http" not in tools.executors and tools.clients == []


async def test_webhook_node_answers_with_synthesized_stand_in() -> None:
    """The webhook node has no mock: the stand-in answers, the success branch is taken and the
    tool events and transcript record ``synthesized``."""
    api = FakeInternalApi()
    config = flow("webhook_failure")
    api.sim_specs["srun_1"] = sim_spec(
        config, caller_turns=["Where is my order?"], original_node_path=[]
    )
    models = Models(
        agent=agent_script([Rule("order", tool="route_to_order_status")]),
        synth=lambda _req: _synth_reply(),
    )
    outcome = await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    assert outcome == "completed"
    result = api.sim_results["srun_1"]
    assert result["answer_source_counts"] == {
        "mock": 0,
        "recorded": 0,
        "synthesized": 1,
        "error": 0,
    }
    tool = api.call_events("call_sim_1", "tool_call")[0]
    assert tool["name"] == "webhook_n_hook0000" and tool["answer_source"] == "synthesized"
    moves = [e["to_node_id"] for e in api.call_events("call_sim_1", "flow_transition")]
    assert "n_found000" in moves and "n_sorry000" not in moves  # the success branch
    said = [text for role, text in api.messages("call_sim_1") if role == "agent"]
    assert "I could not find your order." not in said
    assert result["usage"]["synth"]["input_tokens"] > 0


def _synth_reply() -> Any:
    from worker.textsim.llm import ScriptReply

    return ScriptReply('{"status":"shipped"}')


async def test_agent_sees_the_synthesized_payload() -> None:
    api = FakeInternalApi()
    config = {**_single_prompt_with([http_tool("slots")])}
    api.sim_specs["srun_1"] = sim_spec(
        config, caller_turns=["Any slots?"], settings={"missing_mock_policy": "synthesize"}
    )
    models = Models(
        agent=agent_script(
            [Rule("slots", tool="slots", args={"ref": "r1"})],
            after_tool=lambda req: f"I found {last_tool_output(req)}",
        ),
        synth=lambda _req: _synth_slots(),
    )
    await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    said = [text for role, text in api.messages("call_sim_1") if role == "agent"]
    assert 'I found {"slots":["11:00"]}' in said
    synth_request = models.of("synth")[0].requests[0]
    prompt = " ".join(text for _, text in synth_request.messages())
    assert "slots" in prompt and '"ref"' in prompt


def _synth_slots() -> Any:
    from worker.textsim.llm import ScriptReply

    return ScriptReply('```json\n{"slots": ["11:00"]}\n```')


def _single_prompt_with(tools: list[dict[str, Any]]) -> dict[str, Any]:
    from tests.harness.textsim_support import agent_config

    return agent_config(tools=tools)
