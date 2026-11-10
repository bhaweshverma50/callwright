"""Persona simulations (008 T069, research R6): the simulated caller follows its brief, ends the
call with ``hang_up``, stops at the caller turn limit (default 20, at most 50) and never speaks
as the agent. Also the offline fallback that runs without vendor keys."""

from __future__ import annotations

from typing import Any

import pytest
from callwright_contract.textsim import SimSettings
from pydantic import ValidationError

from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    agent_config,
    deps,
    sim_spec,
)
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.textsim import runner
from worker.textsim.llm import ScriptReply, ScriptRequest, default_factory
from worker.textsim.persona_caller import (
    CONNECTED,
    HANG_UP,
    clean_caller_text,
    instructions,
)

CALL = "call_sim_1"
BRIEF = {
    "goal": "Move my dentist appointment to Friday",
    "known_facts": ["My name is Priya Shah", "The booking is for Tuesday at 9"],
    "temperament": "polite but in a hurry",
    "speaking_style": "short sentences",
    "constraints": ["Do not accept Monday"],
    "opening_line": "Hi, I need to move my appointment.",
}


def chatty(_: ScriptRequest) -> ScriptReply:
    return ScriptReply("Could you check another time?")


def hang_up_on_second_line(request: ScriptRequest) -> ScriptReply:
    if request.count("assistant") >= 1:
        return ScriptReply(tool_calls=((HANG_UP, {"reason": "goal reached"}),))
    return ScriptReply("Friday works, thanks.")


async def persona(
    api: FakeInternalApi, caller: Any, *, brief: Any = BRIEF, settings: Any = None, **kw: Any
) -> Any:
    models = Models(caller=caller)
    spec = sim_spec(agent_config(), mode="persona", persona_brief=brief, **kw)
    if settings is not None:
        spec["settings"] = settings
    api.sim_specs["srun_1"] = spec
    status = await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    return status, api.sim_results.get("srun_1"), models


def caller_lines(api: FakeInternalApi) -> list[str]:
    return [t for r, t in api.messages(CALL) if r == "user"]


async def test_follows_the_brief_and_sees_the_agent_as_the_other_party() -> None:
    api = FakeInternalApi()
    status, result, models = await persona(api, hang_up_on_second_line)
    assert status == "completed" and api.violations == []
    lines = caller_lines(api)
    assert lines[0] == BRIEF["opening_line"]  # the opening line is said as written
    request = models.of("caller")[0].requests[0]
    system = request.messages()[0][1]
    for part in ("Move my dentist appointment to Friday", "Priya Shah", "Do not accept Monday"):
        assert part in system
    roles = [r for r, _ in request.messages()[1:]]
    texts = [t for _, t in request.messages()[1:]]
    assert roles == ["user", "assistant", "user"]  # agent, caller (itself), agent
    assert texts[1] == BRIEF["opening_line"]
    assert result["persona_brief"]["goal"] == BRIEF["goal"]
    assert result["usage"]["caller"]["output_tokens"] > 0


async def test_hang_up_tool_ends_the_session() -> None:
    api = FakeInternalApi()
    _, result, _ = await persona(api, hang_up_on_second_line)
    assert result["end_reason"] == "caller_hung_up"
    # The opening line is said as written; the model's first call then hangs up.
    assert caller_lines(api) == [BRIEF["opening_line"]]
    assert api.call_events(CALL)[-1]["disconnect_reason"] == "user_hangup"


async def test_turn_limit_defaults_to_twenty() -> None:
    api = FakeInternalApi()
    _, result, _ = await persona(api, chatty, settings={})
    assert result["end_reason"] == "turn_limit_reached" and len(caller_lines(api)) == 20


def test_turn_limit_is_one_to_fifty() -> None:
    assert SimSettings().max_caller_turns == 20
    for turns in (0, 51):
        with pytest.raises(ValidationError):
            SimSettings(max_caller_turns=turns)


async def test_explicit_turn_limit() -> None:
    api = FakeInternalApi()
    _, result, _ = await persona(api, chatty, settings={"max_caller_turns": 3})
    assert len(caller_lines(api)) == 3 and result["end_reason"] == "turn_limit_reached"


async def test_never_speaks_as_the_agent() -> None:
    def impostor(request: ScriptRequest) -> ScriptReply:
        if request.count("assistant") >= 2:
            return ScriptReply(tool_calls=((HANG_UP, {"reason": "done"}),))
        return ScriptReply("Agent: How else can I help you today?\nCaller: Friday, please. [sighs]")

    api = FakeInternalApi()
    await persona(api, impostor, brief={"goal": "Reschedule"})
    lines = caller_lines(api)
    assert lines == ["Friday, please.", "Friday, please."]
    assert all("How else can I help" not in line for line in lines)


async def test_only_agent_lines_twice_means_the_caller_hangs_up() -> None:
    api = FakeInternalApi()
    _, result, _ = await persona(
        api, lambda _: ScriptReply("Agent: Thanks for calling!"), brief={"goal": "Ask hours"}
    )
    assert result["end_reason"] == "caller_hung_up" and caller_lines(api) == []


def test_clean_caller_text() -> None:
    assert clean_caller_text("Caller: yes please") == "yes please"
    assert clean_caller_text("Assistant: sure\nI want Friday *pauses*") == "I want Friday"
    assert clean_caller_text('"Thanks."') == "Thanks."


def test_brief_without_optional_fields() -> None:
    text = instructions({"goal": "Ask about hours"})
    assert "Ask about hours" in text and "Facts you know" not in text


async def test_caller_speaks_first_when_the_agent_waits() -> None:
    api = FakeInternalApi()
    models = Models(caller=hang_up_on_second_line)
    spec = sim_spec(
        agent_config(start_speaker="user"), mode="persona", persona_brief={"goal": "Reschedule"}
    )
    api.sim_specs["srun_1"] = spec
    await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    first = models.of("caller")[0].requests[0]
    assert first.messages()[1] == ("user", CONNECTED)
    assert api.messages(CALL)[0] == ("user", "Friday works, thanks.")


async def test_persona_model_comes_from_settings() -> None:
    api = FakeInternalApi()
    settings = {"persona_model": "openai/gpt-5-mini"}
    _, _, models = await persona(api, hang_up_on_second_line, settings=settings)
    [(_, spec, _)] = [b for b in models.built if b[0] == "caller"]
    assert (spec.provider, spec.model) == ("openai", "gpt-5-mini")
    # The launch models only run at their default temperature; others get 0.7.
    assert "temperature" not in spec.options
    registry = AdapterRegistry()
    assert registry.fixed_temperature(VendorSpec("llm", "openai", "gpt-5.1"))
    assert not registry.fixed_temperature(VendorSpec("llm", "openai", "some-other-model"))


async def test_missing_brief_fails_the_run() -> None:
    api = FakeInternalApi()
    status, result, _ = await persona(api, chatty, brief=None)
    assert status == "failed" and "brief" in result["error_message"]


async def test_offline_fallback_without_vendor_keys() -> None:
    """No key for the provider: agent, caller and stand-ins run on deterministic scripts."""
    api = FakeInternalApi()
    models = default_factory(AdapterRegistry(), {"azure_openai": {"api_key": ""}})
    api.sim_specs["srun_1"] = sim_spec(
        agent_config(), mode="persona", persona_brief=BRIEF, settings={}
    )
    status = await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    result = api.sim_results["srun_1"]
    assert status == "completed" and result["end_reason"] == "caller_hung_up"
    assert caller_lines(api) == [BRIEF["opening_line"], *BRIEF["known_facts"]]
    assert result["usage"]["agent"]["offline"] is True
    assert result["usage"]["caller"]["model"] == "azure_openai/gpt-5.1"
