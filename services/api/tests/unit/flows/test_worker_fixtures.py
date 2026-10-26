"""The voice worker's flow scenarios run compiled flows made by this compiler (004 T050).

Graphs live in services/voice-worker/tests/harness/flows/*.graph.json; their compiled form is
committed next to them. ``UPDATE_GOLDEN=1`` rewrites the compiled files.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents.defaults import default_config
from app.flows.compiler import compile_flow
from app.flows.validation import validate

FLOWS = Path(__file__).resolve().parents[4] / "voice-worker" / "tests" / "harness" / "flows"
GRAPHS = sorted(FLOWS.glob("*.graph.json"))
AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("path", GRAPHS, ids=[p.name.removesuffix(".graph.json") for p in GRAPHS])
def test_worker_fixture_is_current(path: Path) -> None:
    graph = json.loads(path.read_text())
    assert [i for i in validate(graph) if i["severity"] == "error"] == []
    config = default_config("flow", "en-US")
    config["prompt"] = "You are the receptionist of Harbour Clinic."
    name = path.name.removesuffix(".graph.json")
    compiled = compile_flow(
        f"flw_01JA0FL0W{name.upper()[:8]:0<8}".ljust(30, "0")[:30], graph, config, {}, compiled_at=AT
    )
    target = FLOWS / f"{name}.compiled.json"
    text = json.dumps({"config": {**config, "flow": {"compiled": compiled}}}, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN") or not target.exists():
        target.write_text(text)
    assert json.loads(target.read_text()) == json.loads(text)
