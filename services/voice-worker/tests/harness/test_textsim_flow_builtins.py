"""Flow agents in text simulations (008) get the built-ins too: schedule_callback answers a
mocked booking (nothing reaches the API), set_language switches the reply language, and an End
node without a line of its own says a goodbye the agent's model writes."""

from __future__ import annotations

import json

from tests.flow_support import Rule
from tests.harness.test_textsim_language import OPTIONS, replies_in_language
from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    agent_script,
    deps,
    flow,
    sim_spec,
)
from worker.textsim import runner
from worker.textsim.llm import ScriptReply, ScriptRequest

CALLBACK = Rule(
    "call me in five minutes",
    tool="schedule_callback",
    args={"in_minutes": 5, "note": "Finish the flight search."},
)


def flow_agent(request: ScriptRequest) -> ScriptReply:
    if (
        not request.tools
        and request.last("user")
        and "call is ending now" in " ".join(t for r, t in request.messages() if r == "system")
    ):
        return ScriptReply("Talk in five minutes then. Bye!")
    script = agent_script(
        [CALLBACK, Rule("that's it", tool="route_to_wrap_up")],
        after_tool=lambda r: "Booked. I'll call you back in five minutes.",
    )
    return script(request)


async def test_flow_simulation_books_a_mocked_callback_and_ends_with_its_own_goodbye() -> None:
    api = FakeInternalApi()
    api.sim_specs["srun_cb"] = sim_spec(
        flow("greeting_end"),
        srun="srun_cb",
        caller_turns=["I'm getting a call, can you call me in five minutes?", "that's it"],
        recorded_tool_outputs=[],
        channel="sip_inbound",
    )
    seen: list[set[str]] = []

    def agent(request: ScriptRequest) -> ScriptReply:
        seen.append(set(request.tools))
        return flow_agent(request)

    status = await runner.run_simulation(api.client(), "srun_cb", deps(api, Models(agent=agent)))
    assert status == "completed"
    assert any({"schedule_callback", "route_to_wrap_up"} <= tools for tools in seen)
    (booked,) = [
        e for e in api.call_events("call_sim_1", "tool_call") if e["name"] == "schedule_callback"
    ]
    assert booked["mocked"] and not booked["is_error"]
    assert json.loads(booked["output"])["scheduled"] is True
    assert not [r for r in api.requests if r.url.path.endswith("/callbacks")]
    agent_lines = [text for role, text in api.messages("call_sim_1") if role == "agent"]
    assert agent_lines[-1] == "Talk in five minutes then. Bye!"
    assert api.violations == []


async def test_flow_simulation_switches_language() -> None:
    api = FakeInternalApi()
    api.sim_specs["srun_fl"] = sim_spec(
        flow("greeting_end"),
        srun="srun_fl",
        caller_turns=["can we speak in hindi please"],
        recorded_tool_outputs=[],
        language_options=OPTIONS,
    )

    def agent(request: ScriptRequest) -> ScriptReply:
        script = agent_script(
            [Rule("hindi please", tool="set_language", args={"language": "hi"})],
            after_tool=lambda r: replies_in_language(r).text,
        )
        return script(request)

    status = await runner.run_simulation(api.client(), "srun_fl", deps(api, Models(agent=agent)))
    assert status == "completed"
    agent_lines = [text for role, text in api.messages("call_sim_1") if role == "agent"]
    assert agent_lines[-1] == "Theek hai, ab hum Hindi mein baat karenge."
    calls = [e for e in api.call_events("call_sim_1", "tool_call") if e["name"] == "set_language"]
    assert calls and not calls[0]["is_error"]
    assert not [r for r in api.requests if r.url.path.endswith("/language")]
