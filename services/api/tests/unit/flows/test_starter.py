"""Starter graph (004 T012, FR-003)."""

from __future__ import annotations

from app.flows.schemas import FlowGraph
from app.flows.starter import starter_graph
from app.flows.validation import validate


def test_starter_graph_has_start_agent_end_and_validates_cleanly() -> None:
    g = starter_graph()
    assert [n["type"] for n in g["nodes"]] == ["start", "agent", "end"]
    assert len(g["edges"]) == 2
    FlowGraph.model_validate(g)
    issues = validate(g)
    assert [i for i in issues if i["severity"] == "error"] == []
    assert issues == []


def test_starter_ids_are_fresh() -> None:
    a, b = starter_graph(), starter_graph()
    assert {n["id"] for n in a["nodes"]}.isdisjoint({n["id"] for n in b["nodes"]})
