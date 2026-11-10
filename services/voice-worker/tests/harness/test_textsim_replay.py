"""Replay simulations (008 T045, research R5): caller turns in order after the agent's opening,
fragment merge, divergence and stop reasons, with the events and result the API receives."""

from __future__ import annotations

from typing import Any

from tests.flow_support import Rule
from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    agent_config,
    agent_script,
    deps,
    flow,
    sim_spec,
)
from worker.textsim import runner
from worker.textsim.replay_caller import normalize_turns, path_diverged

CALL = "call_sim_1"


async def replay(api: FakeInternalApi, config: dict[str, Any], turns: list[Any], **kw: Any) -> Any:
    models = kw.pop("models", None) or Models(
        agent=agent_script([Rule("bye", tool="end_call")], greeting="Welcome to Acme.")
    )
    api.sim_specs["srun_1"] = sim_spec(config, caller_turns=turns, **kw)
    status = await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    return status, api.sim_results.get("srun_1"), models


def test_turns_are_trimmed_and_empty_ones_dropped() -> None:
    assert normalize_turns(["I wanted to book", "  ", "for  two  people"]) == [
        "I wanted to book",
        "for two people",
    ]


def test_path_divergence() -> None:
    original = ["a", "b", "c"]
    assert not path_diverged(["a", "b"], original)
    assert not path_diverged(["a", "b", "c"], original)
    assert path_diverged(["a", "x"], original)
    assert path_diverged(["a", "b", "c", "d"], original)


async def test_agent_first_turns_in_order_until_exhausted() -> None:
    api = FakeInternalApi()
    status, result, _ = await replay(api, agent_config(), ["Hi there", "What are your hours?"])
    assert status == "completed" and api.violations == []
    assert api.messages(CALL) == [
        ("agent", "Hi there, thanks for calling Acme Bank. How can I help?"),
        ("user", "Hi there"),
        ("agent", "Sure, I can help with that."),
        ("user", "What are your hours?"),
        ("agent", "Sure, I can help with that."),
    ]
    turns = [i["turn_index"] for i in api.items(CALL, "message")]
    assert turns == [0, 1, 1, 2, 2]
    assert result["end_reason"] == "caller_turns_exhausted"
    assert result["diverged_at_turn"] is None and result["status"] == "completed"
    events = api.call_events(CALL)
    assert events[0]["type"] == "status" and events[0]["status"] == "in_progress"
    assert events[-1]["status"] == "ended" and events[-1]["disconnect_reason"] == "user_hangup"
    assert events[-2]["type"] == "usage" and events[-2]["usage"]["llm"][0]["input_tokens"] > 0
    assert not api.call_events(CALL, "turn")  # simulated calls carry no latency
    assert all("started_ms" not in i for i in api.items(CALL, "message"))
    assert result["usage"]["agent"]["model"] == "azure_openai/gpt-5.1"


async def test_caller_first_sends_turn_one_before_any_agent_line() -> None:
    api = FakeInternalApi()
    config = agent_config(start_speaker="user")
    await replay(api, config, ["Hello?"])
    assert api.messages(CALL) == [("user", "Hello?"), ("agent", "Sure, I can help with that.")]


async def test_replay_opens_as_the_base_call_did() -> None:
    """The base call's caller spoke first: the replay sends turn 1 before any agent line, even
    though the agent is set to speak first."""
    api = FakeInternalApi()
    await replay(api, agent_config(), ["Hello?"], start_speaker="user")
    assert api.messages(CALL) == [("user", "Hello?"), ("agent", "Sure, I can help with that.")]


async def test_generated_greeting_when_the_agent_has_no_begin_message() -> None:
    api = FakeInternalApi()
    await replay(api, agent_config(begin_message=None), ["Hi"])
    assert api.messages(CALL)[0] == ("agent", "Welcome to Acme.")


async def test_agent_hangup_before_turns_run_out_diverges() -> None:
    api = FakeInternalApi()
    status, result, _ = await replay(api, agent_config(), ["Hi", "ok bye", "one more thing"])
    assert status == "completed"
    assert result["end_reason"] == "agent_hangup" and result["diverged_at_turn"] == 2
    assert "one more thing" not in [t for _, t in api.messages(CALL)]
    assert api.call_events(CALL)[-1]["disconnect_reason"] == "agent_hangup"


async def test_agent_hangup_on_the_last_turn_is_not_a_divergence() -> None:
    api = FakeInternalApi()
    _, result, _ = await replay(api, agent_config(), ["Hi", "bye"])
    assert result["end_reason"] == "agent_hangup" and result["diverged_at_turn"] is None


async def test_goodbye_without_end_call_ends_the_call_like_live() -> None:
    api = FakeInternalApi()
    models = Models(agent=agent_script([Rule("thanks", reply="You're welcome, goodbye!")]))
    _, result, _ = await replay(api, agent_config(), ["thanks", "wait"], models=models)
    assert result["end_reason"] == "agent_hangup" and result["diverged_at_turn"] == 1


async def test_transfer_ends_with_call_transfer() -> None:
    api = FakeInternalApi()
    transfer = {
        "tool_id": "tool_xfer",
        "type": "transfer_call",
        "name": "transfer",
        "description": "Transfer to a person",
        "config": {"routing_type": "static", "number": "+14155550100"},
    }
    models = Models(agent=agent_script([Rule("person", tool="transfer")]))
    _, result, _ = await replay(
        api, agent_config(tools=[transfer]), ["a person please", "hello?"], models=models
    )
    assert result["end_reason"] == "call_transfer" and result["diverged_at_turn"] == 1
    assert api.call_events(CALL)[-1]["disconnect_reason"] == "call_transfer"


async def test_turn_limit_after_fifty_agent_turns() -> None:
    api = FakeInternalApi()
    turns = [f"line {i}" for i in range(55)]
    _, result, _ = await replay(api, agent_config(), turns)
    assert result["end_reason"] == "turn_limit_reached"
    assert len([1 for r, _ in api.messages(CALL) if r == "user"]) == 50
    assert api.call_events(CALL)[-1]["disconnect_reason"] == "user_hangup"


async def test_flow_follows_the_original_path_without_divergence() -> None:
    api = FakeInternalApi()
    models = Models(
        agent=agent_script(
            [Rule("support", tool="route_to_knows_the_need")], classify={"support": "Support"}
        )
    )
    path = ["n_start000", "n_triage00", "n_route000", "n_suppline", "n_end00000"]
    _, result, _ = await replay(
        api,
        flow("triage_support"),
        ["Hi, I need support with my router"],
        original_node_path=path,
        models=models,
    )
    assert result["end_reason"] == "agent_hangup" and result["diverged_at_turn"] is None
    moves = api.call_events(CALL, "flow_transition")
    assert [m["to_node_id"] for m in moves] == path[1:]
    agent_items = [i for i in api.items(CALL, "message") if i["role"] == "agent"]
    assert {i.get("node_id") for i in agent_items} >= {"n_triage00"}


async def test_flow_node_path_divergence_turn() -> None:
    api = FakeInternalApi()
    models = Models(
        agent=agent_script(
            [Rule("support", tool="route_to_knows_the_need")], classify={"support": "Support"}
        )
    )
    original = ["n_start000", "n_triage00", "n_route000", "n_sales000", "n_end00000"]
    _, result, _ = await replay(
        api,
        flow("triage_support"),
        ["Hi, I need support with my router"],
        original_node_path=original,
        models=models,
    )
    assert result["diverged_at_turn"] == 1


async def test_events_409_stops_the_run_with_a_failed_result() -> None:
    api = FakeInternalApi(close_events_after=2)
    status, result, _ = await replay(api, agent_config(), ["one", "two", "three", "four"])
    assert status == "failed" and result["status"] == "failed"
    assert "409" in result["error_message"] and result["end_reason"] == "error"
    assert len([1 for r, _ in api.messages(CALL) if r == "user"]) < 4


async def test_cancelled_run_stops_quietly() -> None:
    api = FakeInternalApi()
    api.sim_specs["srun_1"] = 409
    status = await runner.run_simulation(api.client(), "srun_1", deps(api, Models()))
    assert status == "gone" and api.sim_results == {} and api.events == {}


async def test_agent_model_failure_is_a_failed_run_with_ended_status() -> None:
    def broken(_: Any) -> Any:
        raise RuntimeError("upstream unavailable")

    api = FakeInternalApi()
    status, result, _ = await replay(api, agent_config(), ["Hi"], models=Models(agent=broken))
    assert status == "failed" and result["end_reason"] == "error" and result["error_message"]
    ended = api.call_events(CALL)[-1]
    assert ended["status"] == "ended" and ended["disconnect_reason"] == "error"
