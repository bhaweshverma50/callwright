"""Override resolution, tools and knowledge search in the compiler (004 T073; FR-009 to FR-011)."""

from __future__ import annotations

from typing import Any

from app.agents.defaults import default_config
from app.flows.compiler import compile_flow
from tests.flow_helpers import clinic

FLOW = "flw_01JA0FL0WG0LDEN000000000000"
TOOL_A = "tool_01ARZ3NDEKTSV4RRFFQ69G5FA1"
TOOL_B = "tool_01ARZ3NDEKTSV4RRFFQ69G5FA2"
SPECS = {
    TOOL_A: {"tool_id": TOOL_A, "type": "end_call", "name": "hang_up", "description": "End", "config": {}},
    TOOL_B: {"tool_id": TOOL_B, "type": "end_call", "name": "flow_tool", "description": "End", "config": {}},
}


def _agent(**changes: Any) -> dict[str, Any]:
    cfg = default_config("flow", "en-GB")
    cfg.update(changes)
    return cfg


def test_use_agent_default_follows_the_agent_config() -> None:
    first = compile_flow(FLOW, clinic(), _agent(), SPECS)
    later = compile_flow(
        FLOW, clinic(), _agent(llm={"provider": "openai", "model": "gpt-5-mini", "temperature": 1.0}), SPECS
    )
    assert first["nodes"]["n_triage01"]["llm"]["model"] == "gpt-5.1"
    assert later["nodes"]["n_triage01"]["llm"] == {
        "provider": "openai",
        "model": "gpt-5-mini",
        "temperature": 1.0,
    }


def test_node_override_language_and_voice() -> None:
    g = clinic()
    g["nodes"][1]["config"]["overrides"] = {
        "llm": {"provider": "openai", "model": "gpt-5.2"},
        "tts": {"provider": "cartesia", "voice_id": "voice-x", "speed": 1.2},
        "stt": None,
        "language": "es",
    }
    node = compile_flow(FLOW, g, _agent(), SPECS)["nodes"]["n_triage01"]
    assert node["llm"] == {"provider": "openai", "model": "gpt-5.2", "temperature": 1.0}
    assert (
        node["tts"]["provider"] == "cartesia"
        and node["tts"]["voice_id"] == "voice-x"
        and node["tts"]["speed"] == 1.2
    )
    assert "model" not in node["tts"]  # a new provider never inherits the old provider's model
    assert node["language"] == "es"
    assert node["stt"]["model"] is None  # Auto for the node language
    other = compile_flow(FLOW, g, _agent(), SPECS)["nodes"]["n_details1"]
    assert other["language"] == "en-GB" and other["tts"]["provider"] == "elevenlabs"


def test_node_tools_stay_on_their_node_and_flow_tools_go_everywhere() -> None:
    g = clinic()
    g["nodes"][1]["config"]["tool_ids"] = [TOOL_A]
    compiled = compile_flow(FLOW, g, _agent(tool_ids=[TOOL_B]), SPECS)
    triage = [t["name"] for t in compiled["nodes"]["n_triage01"]["tools"]]
    details = [t["name"] for t in compiled["nodes"]["n_details1"]["tools"]]
    assert triage == ["hang_up", "flow_tool"]
    assert details == ["flow_tool"]


def test_kb_search_follows_flow_knowledge_and_node_switch() -> None:
    kb = "kb_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    compiled = compile_flow(FLOW, clinic(), _agent(kb_ids=[kb]), SPECS)
    assert compiled["nodes"]["n_triage01"]["kb_search"] == {"enabled": True, "kb_ids": [kb]}
    assert compiled["nodes"]["n_details1"]["kb_search"]["enabled"] is False  # switched off on the node
    none = compile_flow(FLOW, clinic(), _agent(), SPECS)
    assert none["nodes"]["n_triage01"]["kb_search"]["enabled"] is False
