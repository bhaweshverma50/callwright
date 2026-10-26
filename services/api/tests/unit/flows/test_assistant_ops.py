"""Assistant operations (004 T085, T113): id remap, apply, cascade, overrides stripped,
placement without overlap and without moving existing nodes."""

from __future__ import annotations

import json
import re

import pytest

from app.flows.assistant import (
    NODE_H,
    NODE_W,
    UnknownReference,
    apply_operations,
    parse_answer,
    place_added,
    remap_ids,
)
from app.flows.assistant_fake import reply
from app.flows.schemas import FlowGraph
from app.llms.adapters.base import ChatMessage
from tests.flow_helpers import basic

NODE_ID = re.compile(r"^n_[a-z0-9]{8}$")
EDGE_ID = re.compile(r"^e_[a-z0-9]{8}$")


def _insert_ops() -> list[dict[str, object]]:
    return [
        {
            "op": "add_node",
            "node": {
                "id": "tmp_1",
                "type": "task",
                "label": "Date of birth",
                "config": {"overrides": {"llm": {"model": "x"}}},
            },
        },
        {"op": "remove_edge", "edge_id": "e_done0000"},
        {
            "op": "add_edge",
            "edge": {
                "source": "n_agent000",
                "target": "tmp_1",
                "trigger": "llm_condition",
                "label": "Ready",
                "condition": "c",
            },
        },
        {"op": "add_edge", "edge": {"source": "tmp_1", "target": "n_end00000", "trigger": "success"}},
    ]


def test_temp_ids_are_remapped_everywhere() -> None:
    ops = remap_ids(basic(), _insert_ops())
    new_id = ops[0]["node"]["id"]  # type: ignore[index]
    assert NODE_ID.match(new_id)
    assert ops[2]["edge"]["target"] == new_id  # type: ignore[index]
    assert ops[3]["edge"]["source"] == new_id  # type: ignore[index]
    assert all(EDGE_ID.match(op["edge"]["id"]) for op in ops if op["op"] == "add_edge")  # type: ignore[index]


def test_apply_insert_strips_overrides_and_validates() -> None:
    g = basic()
    proposed, applied, _ = apply_operations(g, remap_ids(g, _insert_ops()))
    added = next(n for n in proposed["nodes"] if n["label"] == "Date of birth")
    assert "overrides" not in applied[0]["node"]["config"] or applied[0]["node"]["config"]["overrides"] == {
        "llm": None,
        "tts": None,
        "stt": None,
        "language": None,
    }
    assert added["config"]["overrides"] == {"llm": None, "tts": None, "stt": None, "language": None}
    assert [o["op"] for o in applied] == ["add_node", "remove_edge", "add_edge", "add_edge"]
    assert g == basic()  # the input is never modified


def test_remove_node_cascades_to_its_edges() -> None:
    g = basic()
    _, applied, _ = apply_operations(g, [{"op": "remove_node", "node_id": "n_end00000"}])
    assert applied == [
        {"op": "remove_edge", "edge_id": "e_done0000"},
        {"op": "remove_node", "node_id": "n_end00000"},
    ]


def test_update_node_deep_merges_config() -> None:
    g = basic()
    proposed, _, _ = apply_operations(
        g,
        [
            {
                "op": "update_node",
                "node_id": "n_agent000",
                "changes": {"config": {"begin_message": "Hello", "overrides": {"llm": {}}}},
            }
        ],
    )
    cfg = proposed["nodes"][1]["config"]
    assert cfg["begin_message"] == "Hello" and cfg["instructions"] == "Help the caller."
    assert cfg["overrides"]["llm"] is None


@pytest.mark.parametrize(
    "op",
    [
        {"op": "update_node", "node_id": "n_nothere0", "changes": {}},
        {"op": "remove_node", "node_id": "n_nothere0"},
        {"op": "remove_edge", "edge_id": "e_nothere0"},
        {"op": "add_edge", "edge": {"id": "e_new00000", "source": "n_agent000", "target": "n_nothere0"}},
    ],
)
def test_unknown_ids_are_rejected(op: dict[str, object]) -> None:
    with pytest.raises(UnknownReference):
        apply_operations(basic(), [op])


def test_rename_flow() -> None:
    _, applied, name = apply_operations(basic(), [{"op": "rename_flow", "name": "  Clinic v2 "}])
    assert name == "Clinic v2" and applied == [{"op": "rename_flow", "name": "Clinic v2"}]


def _boxes_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["x"] < b["x"] + NODE_W
        and b["x"] < a["x"] + NODE_W
        and a["y"] < b["y"] + NODE_H
        and b["y"] < a["y"] + NODE_H
    )


def test_inserted_node_sits_between_neighbours_without_overlap() -> None:
    g = basic()
    before = {n["id"]: dict(n["position"]) for n in g["nodes"]}
    proposed, applied, _ = apply_operations(g, remap_ids(g, _insert_ops()))
    removed = [e for e in g["edges"] if e["id"] == "e_done0000"]
    place_added(proposed, removed)
    FlowGraph.model_validate(proposed)
    added = next(n for n in proposed["nodes"] if n["id"] == applied[0]["node"]["id"])
    assert 300 <= added["position"]["x"] <= 600  # between Triage (300) and End (600)
    for n in proposed["nodes"]:
        if n["id"] in before:
            assert n["position"] == before[n["id"]]
        else:
            assert not any(
                _boxes_overlap(n["position"], o["position"]) for o in proposed["nodes"] if o is not n
            )


def test_appended_node_goes_right_of_its_neighbour() -> None:
    g = basic()
    ops = remap_ids(
        g,
        [
            {
                "op": "add_node",
                "node": {"id": "tmp_x", "type": "say", "label": "Hello", "config": {"message": "Hi"}},
            },
            {"op": "add_edge", "edge": {"source": "n_end00000", "target": "tmp_x", "trigger": "always"}},
        ],
    )
    proposed, _, _ = apply_operations(g, ops)
    place_added(proposed, [])
    added = proposed["nodes"][-1]
    assert added["position"] == {"x": 600 + NODE_W + 120, "y": 0}


def test_parse_answer_tolerates_fences_and_garbage() -> None:
    assert parse_answer('```json\n{"message": "ok", "operations": []}\n```') == ("ok", None, [])
    message, _, ops = parse_answer("not json")
    assert ops == [] and message


def test_fake_planner_inserts_a_task_between_two_nodes() -> None:
    system = f"<graph>\n{json.dumps(basic())}\n</graph>"
    answer = json.loads(reply([ChatMessage("user", "Add a step that collects the date of birth")], system))
    kinds = [o["op"] for o in answer["operations"]]
    assert kinds.count("add_node") == 1 and kinds.count("remove_edge") == 1 and kinds.count("add_edge") == 2
