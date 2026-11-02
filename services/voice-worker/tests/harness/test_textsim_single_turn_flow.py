"""Single-turn test cases (008 T037, T092): the agent's opening, one caller turn, then the reply,
tool calls and (flow agents) the visited nodes posted as the case result."""

from __future__ import annotations

from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    Rule,
    agent_config,
    agent_script,
    case_spec,
    deps,
    flow,
    http_tool,
    last_tool_output,
)
from worker.textsim import runner

KEY = ("trn_1", "tc_1")


async def test_flow_agent_enters_at_start_follows_a_transition_and_reports_nodes() -> None:
    api = FakeInternalApi()
    api.case_specs[KEY] = case_spec(flow("triage_support"), "Hi, I need support with my router")
    models = Models(
        agent=agent_script(
            [Rule("support", tool="route_to_knows_the_need")], classify={"support": "Support"}
        )
    )
    status = await runner.run_single_turn(api.client(), *KEY, deps(api, models))
    result = api.case_results[KEY]
    assert status == "completed" and result["status"] == "completed"
    assert result["nodes_visited"] == [
        "n_start000",
        "n_triage00",
        "n_route000",
        "n_suppline",
        "n_end00000",
    ]
    assert "Connecting you with support guidance now." in result["agent_response"]
    assert "Hi, thanks for calling" not in result["agent_response"]  # the opening is not the reply
    assert result["tool_calls"] == [] and result["error_message"] is None
    assert result["duration_ms"] >= 0 and result["usage"]["agent"]["input_tokens"] > 0
    assert api.events == {}  # test cases create no call


async def test_flow_agent_without_a_transition_stays_on_the_entry_node() -> None:
    api = FakeInternalApi()
    api.case_specs[KEY] = case_spec(flow("triage_support"), "What is the weather?")
    status = await runner.run_single_turn(api.client(), *KEY, deps(api, Models()))
    result = api.case_results[KEY]
    assert status == "completed" and result["nodes_visited"] == ["n_start000", "n_triage00"]
    assert result["agent_response"] == "Sure, I can help with that."


async def test_single_prompt_reply_with_tool_calls_and_kb_search() -> None:
    api = FakeInternalApi(
        kb_results=[{"chunk_id": "c1", "content": "Open 9 to 5.", "score": 0.9, "file_name": "faq"}]
    )
    config = agent_config(
        tools=[http_tool("orders", mock='{"status":"shipped"}')],
        knowledge=[{"kb_id": "kb_1", "name": "FAQ"}],
        kb_ids=["kb_1"],
    )
    api.case_specs[KEY] = case_spec(config, "Where is order 42 and when are you open?")
    calls = iter([("orders", {"ref": "42"}), ("kb_search", {"query": "opening hours"})])

    def agent(request):  # type: ignore[no-untyped-def]
        from worker.textsim.llm import ScriptReply

        if request.last("user") is None:
            return ScriptReply("Hello!")
        step = next(calls, None)
        if step is not None:
            return ScriptReply(tool_calls=(step,))
        return ScriptReply(f"Done: {last_tool_output(request)}")

    status = await runner.run_single_turn(api.client(), *KEY, deps(api, Models(agent=agent)))
    result = api.case_results[KEY]
    assert status == "completed"
    assert [(t["name"], t["answer_source"]) for t in result["tool_calls"]] == [
        ("orders", "mock"),
        ("kb_search", None),
    ]
    assert result["tool_calls"][0]["arguments"] == {"ref": "42"}
    assert api.kb_requests[0]["call_id"] == "trn_1"  # the test run id stands in for a call id
    assert "Open 9 to 5." in result["agent_response"]
    assert result["nodes_visited"] == []


async def test_dynamic_variables_render_into_the_prompt() -> None:
    api = FakeInternalApi()
    api.case_specs[KEY] = case_spec(
        agent_config(), "Hi", dynamic_variables={"company_name": "Northwind"}
    )
    models = Models()
    await runner.run_single_turn(api.client(), *KEY, deps(api, models))
    system = models.of("agent")[0].requests[0].messages()[0][1]
    assert "receptionist at Northwind" in system


async def test_cancelled_test_run_posts_nothing() -> None:
    api = FakeInternalApi()
    status = await runner.run_single_turn(api.client(), *KEY, deps(api, Models()))
    assert status == "gone" and api.case_results == {}


async def test_unsupported_model_is_an_error_result() -> None:
    api = FakeInternalApi()
    api.case_specs[KEY] = case_spec(agent_config(llm={"provider": "nobody", "model": "x"}), "Hi")
    status = await runner.run_single_turn(api.client(), *KEY, deps(api, Models()))
    result = api.case_results[KEY]
    assert status == "error" and result["status"] == "error"
    assert "UnsupportedVendor" in result["error_message"] and result["agent_response"] is None
