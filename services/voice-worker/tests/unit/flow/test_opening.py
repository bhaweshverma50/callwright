"""The opening of a flow call and per-node components (004 T058, T080)."""

from __future__ import annotations

import copy
from typing import Any

from tests.flow_support import RecordingControl, compiled_config
from tests.harness.runner import build_runtime
from worker.adapters.registry import AdapterRegistry
from worker.flow.nodes.start import opening
from worker.flow.runtime import FlowCall, FlowComponents
from worker.pipeline import plan_session
from worker.tools.registry import build_call_tools


def flow(name: str) -> dict[str, Any]:
    return copy.deepcopy(compiled_config(name)["flow"]["compiled"])


def test_static_greeting_lands_on_the_first_agent() -> None:
    o = opening(flow("triage_support"), {})
    assert (o.start_speaker, o.greeting) == ("agent", "Thanks for calling. How can I help?")
    assert o.entry_node_id == "n_triage00" and o.next is None


def test_leading_say_nodes_join_the_greeting() -> None:
    f = flow("triage_support")
    start = f["nodes"]["n_start000"]["start"]
    start["next"] = "n_suppline"  # Start -> Say -> End
    o = opening(f, {})
    assert (
        o.greeting
        == "Thanks for calling. How can I help? Connecting you with support guidance now."
    )
    assert o.next is not None and o.next[1].target == "n_end00000"


def test_caller_first_with_and_without_a_short_greeting() -> None:
    f = flow("triage_support")
    start = f["nodes"]["n_start000"]["start"]
    start["start_speaker"] = "user"
    assert opening(f, {}).start_speaker == "agent"  # the short greeting plays before listening
    start["greeting"] = ""
    o = opening(f, {})
    assert (o.start_speaker, o.greeting) == ("user", None)


def test_generated_greeting_is_written_by_the_first_node() -> None:
    f = flow("triage_support")
    f["nodes"]["n_start000"]["start"]["greeting_type"] = "generated"
    o = opening(f, {})
    assert (o.start_speaker, o.greeting, o.entry_node_id) == ("agent", None, "n_triage00")


def test_plan_takes_the_opening_from_the_start_node() -> None:
    config = compiled_config("triage_support")
    plan = plan_session(build_runtime(config, {}), AdapterRegistry())
    assert plan.agent_type == "flow" and plan.greeting == "Thanks for calling. How can I help?"


def test_node_overrides_build_their_own_components() -> None:
    config = compiled_config("overrides_context")
    runtime = build_runtime(config, {})
    plan = plan_session(runtime, AdapterRegistry())
    control = RecordingControl()
    built: list[Any] = []
    components = FlowComponents(AdapterRegistry(), lambda spec: built.append(spec) or spec)
    call = FlowCall(
        runtime, control, plan, components=components, base_tools=build_call_tools(runtime, control)
    )  # type: ignore[arg-type]
    spanish = call.node_components(call.run.node("n_spanish0"))
    assert spanish["llm"].model == "gpt-5-mini" and spanish["llm"].provider == "openai"
    assert spanish["stt"].options["language"] == "es"
    assert call.node_components(call.run.node("n_triage00")) == {}
