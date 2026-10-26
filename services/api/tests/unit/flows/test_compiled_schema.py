"""The worker's compiled_schema.json is current, and compiled output matches it (004 T040)."""

from __future__ import annotations

from app.flows import export_schema
from app.flows.compiled import CompiledFlow
from app.flows.compiler import compile_flow
from tests.flow_helpers import clinic
from tests.unit.flows.test_compiler import FLOW_ID, agent_config


def test_committed_schema_is_current() -> None:
    assert export_schema.main(["--check"]) == 0


def test_compiled_output_matches_the_model() -> None:
    CompiledFlow.model_validate(compile_flow(FLOW_ID, clinic(), agent_config(), {}))
