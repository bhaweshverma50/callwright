"""Validator (004 T033, T109): one failing graph per issue code, the passing reference graphs,
stable ordering and the field-level checks from the live UI walkthrough."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.flows.validation import ValidationContext, validate
from tests.flow_helpers import basic, clinic, codes, edge, llm_edge, node

Graph = dict[str, Any]


def _n(g: Graph, nid: str) -> dict[str, Any]:
    return next(n for n in g["nodes"] if n["id"] == nid)


def _e(g: Graph, eid: str) -> dict[str, Any]:
    return next(e for e in g["edges"] if e["id"] == eid)


def two_starts(g: Graph) -> None:
    g["nodes"].append(node("n_start002", "start", "Start 2", 0, 300))


def no_start(g: Graph) -> None:
    g["nodes"] = [n for n in g["nodes"] if n["type"] != "start"]
    g["edges"] = [e for e in g["edges"] if e["id"] != "e_start001"]


def start_incoming(g: Graph) -> None:
    g["edges"].append(llm_edge("e_back0001", "n_triage01", "n_start001", "Go back"))


def start_to_end(g: Graph) -> None:
    _e(g, "e_start001")["target"] = "n_end00001"


def dangling(g: Graph) -> None:
    g["edges"].append(edge("e_gone0001", "n_booked01", "n_missing1"))


def trigger_not_allowed(g: Graph) -> None:
    g["edges"].append(edge("e_bad00001", "n_triage01", "n_end00001", "always"))


def say_two_outgoing(g: Graph) -> None:
    g["edges"].append(edge("e_dup00001", "n_booked01", "n_desk0001"))


def say_no_outgoing(g: Graph) -> None:
    g["edges"] = [e for e in g["edges"] if e["id"] != "e_said0001"]


def one_category(g: Graph) -> None:
    _n(g, "n_route001")["config"]["categories"] = [{"name": "Billing", "description": ""}]
    g["edges"] = [e for e in g["edges"] if e["id"] != "e_rest0001"]


def no_else(g: Graph) -> None:
    g["edges"] = [e for e in g["edges"] if e["id"] != "e_else0001"]


def say_without_message(g: Graph) -> None:
    _n(g, "n_booked01")["config"]["message"] = "  "


def bad_task_schema(g: Graph) -> None:
    _n(g, "n_details1")["config"]["fields"].append(
        {"name": "Bad Name", "type": "string", "description": "", "required": True}
    )


def end_with_edge(g: Graph) -> None:
    g["edges"].append(edge("e_endout01", "n_end00001", "n_triage01"))


def too_many_nodes(g: Graph) -> None:
    for i in range(201 - len(g["nodes"])):
        g["nodes"].append(node(f"n_x{i:07d}", "say", "Filler", message="Hi"))


def unreachable(g: Graph) -> None:
    g["nodes"].append(node("n_island01", "end", "Island", 0, 600))


def no_instructions(g: Graph) -> None:
    _n(g, "n_triage01")["config"]["instructions"] = ""


def agent_stalls(g: Graph) -> None:
    g["edges"] = [e for e in g["edges"] if e["source"] != "n_triage01"]


def no_exit(g: Graph) -> None:
    g["nodes"] = [n for n in g["nodes"] if n["type"] not in ("end", "transfer")]
    g["edges"] = [
        e
        for e in g["edges"]
        if e["target"] not in ("n_end00001", "n_desk0001") and e["source"] != "n_desk0001"
    ]


def transfer_no_fallback(g: Graph) -> None:
    g["edges"] = [e for e in g["edges"] if e["id"] != "e_deskno01"]


def end_no_message(g: Graph) -> None:
    _n(g, "n_end00001")["config"]["message"] = ""


def unset_variable(g: Graph) -> None:
    _n(g, "n_booked01")["config"]["message"] = "Your date of birth is {{dob}}."


def no_begin_message(g: Graph) -> None:
    _n(g, "n_details1")["config"]["begin_message"] = None


def greeting_source(g: Graph) -> None:
    _n(g, "n_start001")["config"]["greeting_type"] = "generated"
    g["nodes"].append(node("n_hello001", "say", "Hello", message="Hello"))
    _e(g, "e_start001")["target"] = "n_hello001"
    g["edges"].append(edge("e_hello001", "n_hello001", "n_triage01"))


def max_rounds_25(g: Graph) -> None:
    _n(g, "n_details1")["config"]["max_rounds"] = 25


def category_name(g: Graph) -> None:
    _n(g, "n_route001")["config"]["categories"].append({"name": "billing", "description": ""})


def label_symbols(g: Graph) -> None:
    _e(g, "e_book0001")["label"] = "!!!"


def unknown_catalog(g: Graph) -> None:
    _n(g, "n_triage01")["config"]["overrides"]["llm"] = {
        "provider": "openai",
        "model": "gpt-0-nope",
        "temperature": 0.5,
    }


CASES: list[tuple[str, Callable[[Graph], None]]] = [
    ("E_START_COUNT", two_starts),
    ("E_START_COUNT", no_start),
    ("E_START_EDGES", start_incoming),
    ("E_START_EDGES", start_to_end),
    ("E_DANGLING_EDGE", dangling),
    ("E_TRIGGER_NOT_ALLOWED", trigger_not_allowed),
    ("E_EDGE_CARDINALITY", say_two_outgoing),
    ("E_MISSING_OUTGOING", say_no_outgoing),
    ("E_CATEGORY_EDGES", one_category),
    ("E_RULE_ELSE", no_else),
    ("E_REQUIRED_FIELD", say_without_message),
    ("E_INVALID_SCHEMA", bad_task_schema),
    ("E_END_HAS_EDGES", end_with_edge),
    ("E_LIMIT", too_many_nodes),
    ("E_GREETING_SOURCE", greeting_source),
    ("E_INVALID_FIELD", max_rounds_25),
    ("E_CATEGORY_NAME", category_name),
    ("E_TRANSITION_NAME_EMPTY", label_symbols),
    ("E_UNKNOWN_CATALOG", unknown_catalog),
    ("W_UNREACHABLE", unreachable),
    ("W_NO_INSTRUCTIONS", no_instructions),
    ("W_NODE_STALLS", agent_stalls),
    ("W_NO_EXIT", no_exit),
    ("W_TRANSFER_NO_FALLBACK", transfer_no_fallback),
    ("W_UNSET_VARIABLE", unset_variable),
    ("W_NO_BEGIN_MESSAGE", no_begin_message),
]


def _context() -> ValidationContext:
    from app.flows.catalogs import check_overrides

    return ValidationContext(check_overrides=check_overrides)


def test_reference_graphs_pass() -> None:
    assert validate(clinic(), _context()) == []
    assert validate(basic(), _context()) == []


@pytest.mark.parametrize(("code", "mutate"), CASES, ids=[f"{c}-{m.__name__}" for c, m in CASES])
def test_each_code_fires(code: str, mutate: Callable[[Graph], None]) -> None:
    g = clinic()
    mutate(g)
    issues = validate(g, _context())
    assert code in codes(issues), issues
    severity = "error" if code.startswith("E_") else "warning"
    assert all(i["severity"] == severity for i in issues if i["code"] == code)


def test_end_without_message_is_valid() -> None:
    """An empty closing message means the agent says its own goodbye: no warning."""
    g = clinic()
    end_no_message(g)
    assert [i for i in validate(g) if i["node_id"] == "n_end00001"] == []


def test_second_start_is_named() -> None:
    g = clinic()
    two_starts(g)
    issue = next(i for i in validate(g) if i["code"] == "E_START_COUNT")
    assert issue["node_id"] == "n_start002"
    assert issue["message"] == "A flow needs exactly one Start node."


def test_errors_come_before_warnings_then_node_order() -> None:
    g = clinic()
    unreachable(g)
    say_without_message(g)
    no_begin_message(g)
    issues = validate(g)
    severities = [i["severity"] for i in issues]
    assert severities == sorted(severities, key=lambda s: s != "error")
    warnings = [i for i in issues if i["severity"] == "warning"]
    order = [n["id"] for n in g["nodes"]]
    assert [order.index(i["node_id"]) for i in warnings] == sorted(
        order.index(i["node_id"]) for i in warnings
    )


def test_spec_us2_scenario_8() -> None:
    """Max rounds 25 and a webhook URL "notaurl" are field errors; an agent without
    instructions is fine while the persona prompt is set."""
    g = clinic()
    max_rounds_25(g)
    _n(g, "n_book0001")["config"]["request"]["url"] = "notaurl"
    no_instructions(g)
    issues = validate(g, ValidationContext(persona_prompt="You are the clinic's receptionist."))
    fields = {(i["node_id"], i["field"]) for i in issues if i["code"] == "E_INVALID_FIELD"}
    assert ("n_details1", "max_rounds") in fields
    assert ("n_book0001", "request.url") in fields
    assert "W_NO_INSTRUCTIONS" not in codes(issues)


@pytest.mark.parametrize("rounds", [0, 25, "5", 2.5])
def test_max_rounds_out_of_range(rounds: Any) -> None:
    g = clinic()
    _n(g, "n_details1")["config"]["max_rounds"] = rounds
    assert "E_INVALID_FIELD" in codes(validate(g))


@pytest.mark.parametrize(("number", "code"), [("12345", "E_INVALID_FIELD"), (None, "E_REQUIRED_FIELD")])
def test_transfer_number(number: str | None, code: str) -> None:
    g = clinic()
    _n(g, "n_desk0001")["config"]["transfer"]["number"] = number
    issue = next(i for i in validate(g) if i["code"] == code)
    assert issue["field"] == "transfer.number"
    if number:
        assert "+14155550100" in issue["message"]


def test_invalid_json_body_and_mock() -> None:
    g = clinic()
    cfg = _n(g, "n_book0001")["config"]
    cfg["request"]["body_template"] = '{"name": '
    cfg["mock_response"] = "not json"
    fields = {i["field"] for i in validate(g) if i["code"] == "E_INVALID_FIELD"}
    assert {"request.body_template", "mock_response"} <= fields


def test_webhook_timeout_range() -> None:
    g = clinic()
    _n(g, "n_book0001")["config"]["request"]["timeout_ms"] = 99
    assert any(i["code"] == "E_INVALID_FIELD" and i["node_id"] == "n_book0001" for i in validate(g))


def test_no_label_needed_on_start_say_and_extract_edges() -> None:
    issues = validate(clinic())
    assert "E_REQUIRED_FIELD" not in codes(issues)


def test_llm_edge_needs_label_and_condition() -> None:
    g = clinic()
    e = _e(g, "e_book0001")
    e["label"] = None
    e["condition"] = ""
    fields = {
        i["field"] for i in validate(g) if i["code"] == "E_REQUIRED_FIELD" and i["edge_id"] == "e_book0001"
    }
    assert fields == {"label", "condition"}


def test_category_rename_breaks_the_old_connection() -> None:
    g = clinic()
    _n(g, "n_route001")["config"]["categories"][0]["name"] = "Payments"
    issues = validate(g)
    assert any(i["code"] == "E_CATEGORY_EDGES" and i["edge_id"] == "e_bill0001" for i in issues)


def test_invalid_category_name_pattern() -> None:
    g = clinic()
    _n(g, "n_route001")["config"]["categories"].append({"name": "!bad", "description": ""})
    assert "E_CATEGORY_NAME" in codes(validate(g))


def test_rule_value_absent_only_for_exists() -> None:
    g = clinic()
    _e(g, "e_rule0001")["rule"] = {"variable": "topic", "operator": "exists", "value": None}
    assert "E_REQUIRED_FIELD" not in codes(validate(g))
    _e(g, "e_rule0001")["rule"] = {"variable": "topic", "operator": "equals", "value": None}
    assert "E_REQUIRED_FIELD" in codes(validate(g))


def test_unknown_tool_reference() -> None:
    g = clinic()
    _n(g, "n_triage01")["config"]["tool_ids"] = ["tool_01ARZ3NDEKTSV4RRFFQ69G5FAV"]
    assert "E_UNKNOWN_TOOL" in codes(validate(g, ValidationContext(tools={})))
    assert "E_UNKNOWN_TOOL" not in codes(validate(g))  # no library given: not checked


def test_greeting_rules() -> None:
    g = basic()
    start = _n(g, "n_start000")["config"]
    start["greeting"] = ""
    assert "E_REQUIRED_FIELD" in codes(validate(g))
    start["start_speaker"] = "user"
    assert validate(g) == []
    start["start_speaker"] = "agent"
    start["greeting_type"] = "generated"
    assert validate(g) == []


def test_validating_200_nodes_is_fast() -> None:
    import time

    g = basic()
    prev = "n_agent000"
    g["edges"] = [e for e in g["edges"] if e["id"] != "e_done0000"]
    for i in range(196):
        nid = f"n_s{i:07d}"
        g["nodes"].append(node(nid, "say", f"Step {i}", message="Hello {{call_id}}"))
        g["edges"].append(
            llm_edge(f"e_s{i:07d}", prev, nid, "Next")
            if prev == "n_agent000"
            else edge(f"e_s{i:07d}", prev, nid)
        )
        prev = nid
    g["edges"].append(edge("e_last0000", prev, "n_end00000"))
    started = time.perf_counter()
    issues = validate(g)
    assert (time.perf_counter() - started) < 0.05
    assert [i for i in issues if i["severity"] == "error"] == []
