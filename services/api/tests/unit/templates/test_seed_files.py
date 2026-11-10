"""Template seed files (T069): parse, unique slugs, every category used, valid when overlaid."""

from __future__ import annotations

import re

import pytest

from app.agents.offered import template_overlay
from app.agents.validation import validate_pure
from app.flows import compiler, validation
from app.templates.jobs import load_seed
from app.templates.service import CATEGORIES

SEEDS = load_seed()


def test_unique_slugs_and_categories() -> None:
    ids = [t["id"] for t in SEEDS]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9-]{3,64}", i) for i in ids)
    assert {t["category"] for t in SEEDS} == set(CATEGORIES)


@pytest.mark.parametrize("seed", SEEDS, ids=[t["id"] for t in SEEDS])
def test_overlay_validates(seed: dict) -> None:  # type: ignore[type-arg]
    overlay, warnings = template_overlay(seed["config"])
    assert warnings == []
    assert seed["agent_type"] in {"single_prompt", "flow"}
    result = validate_pure(seed["agent_type"], overlay)
    assert result.valid, result.errors
    assert result.publish_blockers == []
    assert "graph" not in overlay and "agent_name" not in overlay
    assert len(seed["name"]) <= 80 and len(seed["description"]) <= 300
    assert seed["direction"] in {"inbound", "outbound"}


def test_every_category_has_both_directions_and_both_types() -> None:
    seen = {(t["category"], t["direction"]) for t in SEEDS}
    assert seen == {(c, d) for c in CATEGORIES for d in ("inbound", "outbound")}
    assert {t["agent_type"] for t in SEEDS} == {"single_prompt", "flow"}
    assert sum(1 for t in SEEDS if t["agent_type"] == "flow") >= 8


FLOWS = [t for t in SEEDS if t["agent_type"] == "flow"]


@pytest.mark.parametrize("seed", FLOWS, ids=[t["id"] for t in FLOWS])
def test_flow_graph_validates_and_compiles(seed: dict) -> None:  # type: ignore[type-arg]
    cfg = seed["config"]
    ctx = validation.ValidationContext(
        persona_prompt=cfg["prompt"],
        defaulted_variables=frozenset(v["name"] for v in cfg["dynamic_variables"]),
    )
    issues = validation.validate(cfg["graph"], ctx)
    assert issues == [], issues
    overlay, _ = template_overlay(cfg)
    agent_config = validate_pure("flow", overlay).normalized_config
    compiled = compiler.compile_flow("flw_seed", cfg["graph"], agent_config, {})
    assert compiled["entry_node_id"] in compiled["nodes"]
    assert len(compiled["nodes"]) == len(cfg["graph"]["nodes"])
    types = {n["type"] for n in cfg["graph"]["nodes"]}
    assert {"start", "end"} <= types
    assert not any(
        n["type"] == "webhook"
        or (n["type"] == "transfer" and n["config"]["transfer"]["routing_type"] != "static")
        for n in cfg["graph"]["nodes"]
    )
