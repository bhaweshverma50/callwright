"""Compiler golden files and graph hash (004 T035; data-model section 4)."""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.defaults import default_config
from app.flows.compiler import compile_flow, graph_hash
from tests.flow_helpers import clinic

GOLDEN = Path(__file__).parent / "golden"
AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
FLOW_ID = "flw_01JA0FL0WG0LDEN000000000000"


def agent_config() -> dict[str, Any]:
    cfg = default_config("flow", "en-GB")
    cfg["prompt"] = "You are the receptionist of Harbour Clinic."
    return cfg


def _check(name: str, compiled: dict[str, Any]) -> None:
    path = GOLDEN / f"{name}.compiled.json"
    text = json.dumps(compiled, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.write_text(text)
    assert json.loads(path.read_text()) == json.loads(text)


def test_clinic_golden() -> None:
    graph = (
        json.loads((GOLDEN / "clinic_v2.graph.json").read_text())
        if (GOLDEN / "clinic_v2.graph.json").exists()
        else clinic()
    )
    _check("clinic_v2", compile_flow(FLOW_ID, graph, agent_config(), {}, compiled_at=AT))


def test_hash_is_stable_and_ignores_layout() -> None:
    g = clinic()
    moved = copy.deepcopy(g)
    for n in moved["nodes"]:
        n["position"] = {"x": n["position"]["x"] + 50, "y": -n["position"]["y"]}
    moved["viewport"] = {"x": 10, "y": 20, "zoom": 2}
    assert graph_hash(g) == graph_hash(moved) == graph_hash(clinic())
    changed = copy.deepcopy(g)
    changed["nodes"][1]["label"] = "Front door"
    assert graph_hash(changed) != graph_hash(g)


def test_compiled_shape() -> None:
    compiled = compile_flow(FLOW_ID, clinic(), agent_config(), {}, compiled_at=AT)
    assert compiled["schema_version"] == 1
    assert compiled["entry_node_id"] == "n_start001"
    triage = compiled["nodes"]["n_triage01"]
    assert triage["instructions"].startswith("You are the receptionist of Harbour Clinic.\n\n")
    assert [t["function_name"] for t in triage["transitions"]] == [
        "route_to_book_a_visit",
        "route_to_something_else",
    ]
    assert (
        triage["transitions"][0]["description"]
        == "Go to Collect details. Use when: The caller wants to book an appointment"
    )
    assert triage["llm"] == {k: agent_config()["llm"][k] for k in ("provider", "model", "temperature")}
    task = compiled["nodes"]["n_details1"]["task"]
    assert task["success_target"] == "n_book0001" and task["max_rounds"] == 5
    assert task["json_schema"]["properties"]["day"] == {
        "type": "string",
        "enum": ["monday", "tuesday"],
        "description": "Preferred day",
    }
    assert compiled["nodes"]["n_book0001"]["webhook"]["failure_target"] == "n_desk0001"
    rule = compiled["nodes"]["n_check001"]["condition"]
    assert rule["rules"][0]["variable"] == "topic" and rule["else_target"] == "n_end00001"
    assert {"name": "booking_ref", "source_node_id": "n_book0001", "type": "string"} in compiled[
        "declared_variables"
    ]
    assert compiled["nodes"]["n_start001"]["start"]["next"] == "n_triage01"
