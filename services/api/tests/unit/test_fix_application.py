"""``apply_fix(snapshot, kind, payload)`` per kind (009 T026, written before T029; research R4)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.issues.fixes import AdvisoryFix, InvalidFix, RedraftNeeded, apply_fix, guardrail_text
from app.simulator.targets import canonical_hash

PROMPT = "You book cleanings for Bright Smiles.\n\n## Style\n- Be brief."
TOOL = {
    "tool_id": "tool_01PRICES",
    "type": "http",
    "name": "lookup_price",
    "description": "Look up a price.",
    "config": {"method": "GET"},
    "mock_response": "{}",
}
OTHER_TOOL = {**TOOL, "tool_id": "tool_01HOURS", "name": "opening_hours", "description": "Hours."}


def single() -> dict[str, Any]:
    return {
        "type": "single_prompt",
        "prompt": PROMPT,
        "tool_ids": ["tool_01PRICES"],
        "tools": [copy.deepcopy(TOOL)],
        "kb_ids": ["kb_01A"],
        "knowledge": [{"kb_id": "kb_01A", "name": "FAQ"}],
    }


def node(nid: str, ntype: str = "agent", instructions: str = "", tool_ids: list[str] | None = None) -> Any:
    return {
        "id": nid,
        "type": ntype,
        "label": nid.title(),
        "position": {"x": 0, "y": 0},
        "config": {"instructions": instructions, "tool_ids": tool_ids or []},
    }


def flow() -> dict[str, Any]:
    graph = {
        "nodes": [
            node("n_start000", "start"),
            node("n_greet000", instructions="Greet the caller."),
            node("n_book0000", instructions="Collect the address.", tool_ids=["tool_01PRICES"]),
            node("n_end00000", "end"),
        ],
        "edges": [
            {"id": "e_0000001", "source": "n_start000", "target": "n_greet000", "trigger": "always"},
            {
                "id": "e_0000002",
                "source": "n_greet000",
                "target": "n_book0000",
                "trigger": "llm_condition",
                "label": "wants_booking",
                "condition": "The caller wants to book.",
                "sort_order": 1,
            },
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    compiled = {
        "entry_node_id": "n_start000",
        "graph_hash": "g1",
        "nodes": {
            "n_greet000": {"type": "agent", "tools": [copy.deepcopy(OTHER_TOOL)]},
            "n_book0000": {"type": "agent", "tools": [copy.deepcopy(TOOL)]},
        },
    }
    return {
        "type": "flow",
        "prompt": "You are the clinic scheduler.",
        "tool_ids": ["tool_01HOURS"],
        "tools": [copy.deepcopy(OTHER_TOOL)],
        "kb_ids": [],
        "flow": {
            "flow_id": "flw_1",
            "name": "Clinic",
            "graph": graph,
            "graph_hash": "g1",
            "compiled": compiled,
        },
    }


def graph_node(config: dict[str, Any], nid: str) -> dict[str, Any]:
    found: dict[str, Any] = next(n for n in config["flow"]["graph"]["nodes"] if n["id"] == nid)
    return found


# prompt_edit -------------------------------------------------------------------------------------


def test_prompt_edit_replaces_prompt_and_leaves_input_untouched() -> None:
    base = single()
    before = copy.deepcopy(base)
    out = apply_fix(base, "prompt_edit", {"current_prompt": PROMPT, "proposed_prompt": "New prompt."})
    assert out["prompt"] == "New prompt."
    assert base == before
    assert {k: v for k, v in out.items() if k != "prompt"} == {k: v for k, v in base.items() if k != "prompt"}


def test_prompt_edit_needs_redraft_when_prompt_changed() -> None:
    with pytest.raises(RedraftNeeded):
        apply_fix(single(), "prompt_edit", {"current_prompt": "Old text", "proposed_prompt": "New"})


def test_prompt_edit_ignores_surrounding_whitespace_in_current() -> None:
    out = apply_fix(single(), "prompt_edit", {"current_prompt": PROMPT + "\n", "proposed_prompt": "New"})
    assert out["prompt"] == "New"


def test_prompt_edit_on_flow_forces_recompile() -> None:
    base = flow()
    out = apply_fix(
        base, "prompt_edit", {"current_prompt": base["prompt"], "proposed_prompt": "You schedule visits."}
    )
    assert out["flow"]["compiled"] is None
    assert out["flow"]["graph"] == base["flow"]["graph"]


# node_prompt_edit --------------------------------------------------------------------------------


def test_node_prompt_edit_replaces_instructions_and_recompiles() -> None:
    out = apply_fix(
        flow(),
        "node_prompt_edit",
        {
            "node_id": "n_book0000",
            "current_instructions": "Collect the address.",
            "proposed_instructions": "Collect and read back the address.",
        },
    )
    assert graph_node(out, "n_book0000")["config"]["instructions"] == "Collect and read back the address."
    assert graph_node(out, "n_greet000")["config"]["instructions"] == "Greet the caller."
    assert out["flow"]["compiled"] is None


def test_node_prompt_edit_redraft_when_node_removed_or_edited() -> None:
    payload = {"node_id": "n_gone0000", "current_instructions": "x", "proposed_instructions": "y"}
    with pytest.raises(RedraftNeeded):
        apply_fix(flow(), "node_prompt_edit", payload)
    payload = {"node_id": "n_book0000", "current_instructions": "Old", "proposed_instructions": "y"}
    with pytest.raises(RedraftNeeded):
        apply_fix(flow(), "node_prompt_edit", payload)


def test_node_prompt_edit_refuses_non_conversational_node() -> None:
    payload = {"node_id": "n_end00000", "current_instructions": "", "proposed_instructions": "y"}
    with pytest.raises(InvalidFix):
        apply_fix(flow(), "node_prompt_edit", payload)


# add_guardrail -----------------------------------------------------------------------------------


RULE = "Only quote prices from the price list."


def test_guardrail_appends_rules_section_to_prompt() -> None:
    out = apply_fix(single(), "add_guardrail", {"placement": "agent_prompt", "rule_text": RULE})
    assert out["prompt"] == PROMPT + "\n\n## Rules\n- " + RULE


def test_guardrail_goes_into_existing_rules_section() -> None:
    base = single()
    base["prompt"] = "Intro.\n\n## Rules\n- Be kind.\n\n## Style\n- Short."
    out = apply_fix(base, "add_guardrail", {"placement": "agent_prompt", "rule_text": RULE})
    assert out["prompt"] == f"Intro.\n\n## Rules\n- Be kind.\n- {RULE}\n\n## Style\n- Short."


def test_guardrail_is_idempotent() -> None:
    payload = {"placement": "agent_prompt", "rule_text": RULE}
    once = apply_fix(single(), "add_guardrail", payload)
    twice = apply_fix(once, "add_guardrail", payload)
    assert once == twice
    assert canonical_hash(once) == canonical_hash(twice)


def test_guardrail_text_helper() -> None:
    assert guardrail_text("", RULE) == f"## Rules\n- {RULE}"
    assert guardrail_text(f"## Rules\n- {RULE}", RULE) == f"## Rules\n- {RULE}"


def test_guardrail_on_one_node_and_on_all_agent_nodes() -> None:
    out = apply_fix(
        flow(), "add_guardrail", {"placement": "node", "node_id": "n_book0000", "rule_text": RULE}
    )
    assert graph_node(out, "n_book0000")["config"]["instructions"].endswith(f"## Rules\n- {RULE}")
    assert graph_node(out, "n_greet000")["config"]["instructions"] == "Greet the caller."
    assert out["flow"]["compiled"] is None
    out = apply_fix(flow(), "add_guardrail", {"placement": "all_agent_nodes", "rule_text": RULE})
    for nid in ("n_book0000", "n_greet000"):
        assert graph_node(out, nid)["config"]["instructions"].endswith(f"- {RULE}")
    assert graph_node(out, "n_end00000")["config"]["instructions"] == ""


def test_guardrail_node_must_exist() -> None:
    with pytest.raises(RedraftNeeded):
        apply_fix(flow(), "add_guardrail", {"placement": "node", "node_id": "n_nope0000", "rule_text": RULE})


def test_guardrail_on_nodes_of_single_prompt_agent_is_invalid() -> None:
    with pytest.raises(InvalidFix):
        apply_fix(single(), "add_guardrail", {"placement": "all_agent_nodes", "rule_text": RULE})


# tool_description_edit ---------------------------------------------------------------------------


def test_tool_description_edit_updates_snapshot_tools() -> None:
    payload = {
        "tool_id": "tool_01PRICES",
        "current_description": "Look up a price.",
        "proposed_description": "Look up the listed price of a service.",
    }
    out = apply_fix(single(), "tool_description_edit", payload)
    assert out["tools"][0]["description"] == "Look up the listed price of a service."
    assert out["tools"][0]["name"] == "lookup_price"


def test_tool_description_edit_patches_compiled_flow_nodes_without_recompiling() -> None:
    payload = {
        "tool_id": "tool_01PRICES",
        "current_description": "Look up a price.",
        "proposed_description": "Listed prices only.",
    }
    out = apply_fix(flow(), "tool_description_edit", payload)
    compiled = out["flow"]["compiled"]
    assert compiled is not None
    assert compiled["nodes"]["n_book0000"]["tools"][0]["description"] == "Listed prices only."
    assert compiled["nodes"]["n_greet000"]["tools"][0]["description"] == "Hours."


def test_tool_description_edit_redraft_and_unknown_tool() -> None:
    with pytest.raises(RedraftNeeded):
        apply_fix(
            single(),
            "tool_description_edit",
            {"tool_id": "tool_01PRICES", "current_description": "Changed", "proposed_description": "x"},
        )
    with pytest.raises(RedraftNeeded):
        apply_fix(
            single(),
            "tool_description_edit",
            {"tool_id": "tool_01NOPE", "current_description": "", "proposed_description": "x"},
        )


# transitions -------------------------------------------------------------------------------------


def test_transition_condition_edit() -> None:
    payload = {
        "edge_id": "e_0000002",
        "current_condition": "The caller wants to book.",
        "proposed_condition": "The caller asked to book and gave a day.",
    }
    out = apply_fix(flow(), "transition_condition_edit", payload)
    edge = next(e for e in out["flow"]["graph"]["edges"] if e["id"] == "e_0000002")
    assert edge["condition"] == "The caller asked to book and gave a day."
    assert out["flow"]["compiled"] is None
    with pytest.raises(RedraftNeeded):
        apply_fix(flow(), "transition_condition_edit", {**payload, "current_condition": "Other"})
    with pytest.raises(InvalidFix):
        apply_fix(
            flow(), "transition_condition_edit", {**payload, "edge_id": "e_0000001", "current_condition": ""}
        )


def test_add_transition_appends_edge_with_stable_id() -> None:
    payload = {
        "source_node_id": "n_book0000",
        "target_node_id": "n_end00000",
        "edge_label": "caller_done",
        "handoff_condition": "The caller has nothing else.",
    }
    out = apply_fix(flow(), "add_transition", payload)
    again = apply_fix(flow(), "add_transition", payload)
    edges = out["flow"]["graph"]["edges"]
    assert len(edges) == 3
    new = edges[-1]
    assert new["source"] == "n_book0000" and new["target"] == "n_end00000"
    assert new["trigger"] == "llm_condition" and new["label"] == "caller_done"
    assert new["condition"] == "The caller has nothing else."
    assert new["id"].startswith("e_") and len(new["id"]) == 10
    assert new == again["flow"]["graph"]["edges"][-1]
    assert out["flow"]["compiled"] is None


def test_add_transition_label_must_be_unique_per_source() -> None:
    payload = {
        "source_node_id": "n_greet000",
        "target_node_id": "n_end00000",
        "edge_label": "wants_booking",
        "handoff_condition": "x",
    }
    with pytest.raises(InvalidFix):
        apply_fix(flow(), "add_transition", payload)
    # The same label from another node is fine.
    apply_fix(flow(), "add_transition", {**payload, "source_node_id": "n_book0000"})


def test_add_transition_nodes_must_exist() -> None:
    payload = {
        "source_node_id": "n_book0000",
        "target_node_id": "n_nope0000",
        "edge_label": "go",
        "handoff_condition": "x",
    }
    with pytest.raises(RedraftNeeded):
        apply_fix(flow(), "add_transition", payload)


# node_tool_attachment ----------------------------------------------------------------------------


def test_node_tool_attachment_attach_and_detach() -> None:
    out = apply_fix(
        flow(),
        "node_tool_attachment",
        {"node_id": "n_book0000", "tools_to_attach": ["tool_01HOURS"], "tools_to_detach": ["tool_01PRICES"]},
    )
    assert graph_node(out, "n_book0000")["config"]["tool_ids"] == ["tool_01HOURS"]
    assert out["flow"]["compiled"] is None


def test_node_tool_attachment_requires_agent_tools() -> None:
    with pytest.raises(InvalidFix):
        apply_fix(
            flow(),
            "node_tool_attachment",
            {"node_id": "n_book0000", "tools_to_attach": ["tool_01UNKNOWN"], "tools_to_detach": []},
        )
    with pytest.raises(RedraftNeeded):
        apply_fix(
            flow(),
            "node_tool_attachment",
            {"node_id": "n_greet000", "tools_to_attach": [], "tools_to_detach": ["tool_01PRICES"]},
        )


# kb_attach ---------------------------------------------------------------------------------------


def test_kb_attach_extends_kb_ids_and_drops_stale_knowledge_block() -> None:
    out = apply_fix(single(), "kb_attach", {"kb_ids_to_attach": ["kb_01B", "kb_01A"], "uncovered_topics": []})
    assert out["kb_ids"] == ["kb_01A", "kb_01B"]
    assert "knowledge" not in out


def test_kb_attach_without_knowledge_bases_is_advisory() -> None:
    with pytest.raises(AdvisoryFix):
        apply_fix(single(), "kb_attach", {"kb_ids_to_attach": [], "uncovered_topics": ["Parking"]})


# hashing -----------------------------------------------------------------------------------------


def test_variant_hash_is_stable_across_key_order() -> None:
    payload = {"current_prompt": PROMPT, "proposed_prompt": "New prompt."}
    a = apply_fix(single(), "prompt_edit", payload)
    reordered = dict(reversed(list(single().items())))
    b = apply_fix(reordered, "prompt_edit", dict(reversed(list(payload.items()))))
    assert canonical_hash(a) == canonical_hash(b)
    assert canonical_hash(a) != canonical_hash(single())


def test_unknown_kind_is_invalid() -> None:
    with pytest.raises(InvalidFix):
        apply_fix(single(), "rewrite_everything", {})
