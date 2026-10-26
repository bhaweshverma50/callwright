"""Transition names and descriptions (004 T034, T109; FR-044, research R7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.flows import transitions
from app.flows.validation import validate
from tests.flow_helpers import basic, codes, llm_edge, node

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "transition_names.json").read_text())["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["label"] or "empty" for v in VECTORS])
def test_shared_vectors(vector: dict[str, str | None]) -> None:
    assert transitions.derive_name(vector["label"]) == vector["name"]


def test_prefix_is_never_doubled() -> None:
    assert (
        transitions.derive_name("Route To Billing!")
        == transitions.derive_name("Route to billing")
        == "route_to_billing"
    )


def test_override_wins_over_the_label() -> None:
    assert transitions.function_name("Billing", "route_to_accounts") == "route_to_accounts"


def test_description_names_the_target_and_condition() -> None:
    assert (
        transitions.description("Billing", "caller asks about a bill")
        == "Go to Billing. Use when: caller asks about a bill"
    )


def test_two_labels_with_the_same_name_clash() -> None:
    g = basic()
    g["nodes"].append(node("n_bill0000", "end", "Billing end", 600, 200))
    g["edges"].append(llm_edge("e_bill0000", "n_agent000", "n_bill0000", "caller is done!"))
    issues = validate(g)
    assert "E_FUNCTION_NAME_CLASH" in codes(issues)
    clash = next(i for i in issues if i["code"] == "E_FUNCTION_NAME_CLASH")
    assert clash["edge_id"] == "e_bill0000"


def test_a_name_equal_to_a_tool_name_clashes() -> None:
    from app.flows.validation import ValidationContext

    g = basic()
    g["nodes"][1]["config"]["tool_ids"] = ["tool_01ARZ3NDEKTSV4RRFFQ69G5FAV"]
    ctx = ValidationContext(tools={"tool_01ARZ3NDEKTSV4RRFFQ69G5FAV": "route_to_caller_is_done"})
    assert "E_FUNCTION_NAME_CLASH" in codes(validate(g, ctx))
