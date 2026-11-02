"""Spans and heartbeats of text simulations (008 T088): runs carry ``simulation_run_id`` or
``test_run_id`` and ``call_id``; events are posted while turns run, not only at the end."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.harness.textsim_support import (
    FakeInternalApi,
    Models,
    Rule,
    agent_config,
    agent_script,
    case_spec,
    deps,
    http_tool,
    sim_spec,
)
from worker import telemetry
from worker.textsim import runner


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(telemetry.CallIdSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.install(provider, framework=False)
    yield exporter
    telemetry.install(None)


async def test_simulation_spans_carry_run_and_call_ids(spans: InMemorySpanExporter) -> None:
    api = FakeInternalApi()
    config = agent_config(tools=[http_tool("orders", mock='{"ok":true}')])
    api.sim_specs["srun_1"] = sim_spec(config, caller_turns=["order please", "thanks"])
    models = Models(agent=agent_script([Rule("order", tool="orders")]))
    await runner.run_simulation(api.client(), "srun_1", deps(api, models))
    finished = spans.get_finished_spans()
    [root] = [s for s in finished if s.name == "textsim.simulation"]
    assert dict(root.attributes or {})["simulation_run_id"] == "srun_1"
    assert dict(root.attributes or {})["call_id"] == "call_sim_1"
    assert dict(root.attributes or {})["simulation.end_reason"] == "caller_turns_exhausted"
    turns = [s for s in finished if s.name == "textsim.turn"]
    assert [dict(s.attributes or {})["turn_index"] for s in turns] == [1, 2]
    assert all(dict(s.attributes or {})["call_id"] == "call_sim_1" for s in turns)
    [tool] = [s for s in finished if s.name == "tool.execute"]
    assert dict(tool.attributes or {})["call_id"] == "call_sim_1"


async def test_test_case_span_carries_test_run_id(spans: InMemorySpanExporter) -> None:
    api = FakeInternalApi()
    api.case_specs[("trn_1", "tc_1")] = case_spec(agent_config(), "Hi")
    await runner.run_single_turn(api.client(), "trn_1", "tc_1", deps(api, Models()))
    [root] = [s for s in spans.get_finished_spans() if s.name == "textsim.test_case"]
    assert dict(root.attributes or {})["test_run_id"] == "trn_1"
    assert dict(root.attributes or {})["test_case_id"] == "tc_1"
    assert dict(root.attributes or {})["call_id"] == "trn_1"


async def test_events_are_posted_per_turn_and_as_heartbeats() -> None:
    api = FakeInternalApi()
    api.sim_specs["srun_1"] = sim_spec(agent_config(), caller_turns=["a", "b", "c"])
    fast = dataclasses.replace(deps(api, Models()), heartbeat_interval_s=0.005)
    await runner.run_simulation(api.client(), "srun_1", fast)
    # in_progress, one batch per agent turn (opening and three replies), the final batch,
    # plus heartbeats while turns ran.
    assert api.posts > 6
    assert api.violations == []
    statuses = [e["status"] for e in api.call_events("call_sim_1", "status")]
    assert statuses == ["in_progress", "ended"]
