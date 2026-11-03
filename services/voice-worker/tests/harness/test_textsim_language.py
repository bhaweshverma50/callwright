"""Caller language in text simulations (012): set_language switches the agent's reply language
(instructions only, no speech recognition) so test cases and simulations can exercise it, and
nothing is reported to the API (no preference is ever saved from a simulation)."""

from __future__ import annotations

from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    Rule,
    agent_config,
    agent_script,
    case_spec,
    deps,
    sim_spec,
)
from worker.textsim import runner
from worker.textsim.llm import ScriptReply, ScriptRequest

OPTIONS = [
    {
        "code": "en-US",
        "label": "English (US)",
        "stt_model": "nova-3",
        "tts_model": "eleven_multilingual_v2",
    },
    {"code": "hi", "label": "Hindi", "stt_model": "nova-2", "tts_model": "eleven_multilingual_v2"},
]


def system_text(request: ScriptRequest) -> str:
    return " ".join(text for role, text in request.messages() if role in ("system", "developer"))


def replies_in_language(request: ScriptRequest) -> ScriptReply:
    """Answers in Hindi once the instructions say so (what a real model does)."""
    if "reply only in Hindi" in system_text(request):
        return ScriptReply("Theek hai, ab hum Hindi mein baat karenge.")
    return ScriptReply("Sure, I can help with that.")


async def test_simulation_switches_reply_language_without_reporting() -> None:
    api = FakeInternalApi()
    api.sim_specs["srun_lang"] = sim_spec(
        agent_config(),
        caller_turns=["can we speak in hindi please", "mera order kahan hai"],
        recorded_tool_outputs=[],
        language_options=OPTIONS,
    )
    seen_tools: list[set[str]] = []

    def agent(request: ScriptRequest) -> ScriptReply:
        seen_tools.append(set(request.tools))
        script = agent_script(
            [Rule("hindi please", tool="set_language", args={"language": "hi"})],
            after_tool=lambda r: replies_in_language(r).text,
        )
        reply = script(request)
        if reply.tool_calls or request.after_tool_output or request.last("user") is None:
            return reply
        return replies_in_language(request)

    status = await runner.run_simulation(api.client(), "srun_lang", deps(api, Models(agent=agent)))
    assert status == "completed"
    assert all("set_language" in tools for tools in seen_tools)
    agent_lines = [text for role, text in api.messages("call_sim_1") if role == "agent"]
    assert agent_lines[-2:] == [
        "Theek hai, ab hum Hindi mein baat karenge.",
        "Theek hai, ab hum Hindi mein baat karenge.",
    ]
    calls = [e for e in api.call_events("call_sim_1", "tool_call") if e["name"] == "set_language"]
    assert calls and calls[0]["arguments"] == {"language": "hi"} and not calls[0]["is_error"]
    switched = [
        i for i in api.items("call_sim_1", "system") if i.get("event") == "language_switched"
    ]
    assert switched and switched[0]["detail"] == "Hindi (hi)"
    assert not [r for r in api.requests if r.url.path.endswith("/language")]
    assert api.violations == []


async def test_test_case_without_options_has_no_set_language() -> None:
    api = FakeInternalApi()
    api.case_specs[("trn_l", "tc_l")] = case_spec(agent_config(), "Hindi please")
    seen: list[set[str]] = []

    def agent(request: ScriptRequest) -> ScriptReply:
        seen.append(set(request.tools))
        return ScriptReply("Sure.")

    status = await runner.run_single_turn(
        api.client(), "trn_l", "tc_l", deps(api, Models(agent=agent))
    )
    assert status == "completed" and seen and all("set_language" not in t for t in seen)
