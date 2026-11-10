"""A compiled flow is checked against the API's schema before the call starts (004 T040)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.flow_support import compiled_config
from worker.flow import FlowRuntimeUnavailable
from worker.flow.compiled import SCHEMA_VERSION, load_compiled


def compiled() -> dict[str, Any]:
    config = copy.deepcopy(compiled_config("greeting_end"))
    flow: dict[str, Any] = config["flow"]["compiled"]
    return flow


def test_a_compiled_flow_from_the_api_loads() -> None:
    flow = compiled()
    assert flow["schema_version"] == SCHEMA_VERSION
    assert load_compiled({"flow": {"compiled": flow}}) == flow


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda f: f.pop("entry_node_id"), "entry_node_id is required"),
        (lambda f: f.update(graph_hash="not-a-hash"), "flow.graph_hash has the wrong format"),
        (lambda f: f["nodes"]["n_end00000"].update(type="hangup"), "n_end00000.type must be one"),
        (
            lambda f: f["nodes"]["n_greet000"]["transitions"][0].update(trigger="always"),
            "n_greet000.transitions has the wrong form",
        ),
        (lambda f: f["nodes"]["n_greet000"].update(tools="none"), "tools has the wrong form"),
    ],
)
def test_a_flow_that_does_not_match_the_schema_is_not_run(change: Any, problem: str) -> None:
    flow = compiled()
    change(flow)
    with pytest.raises(FlowRuntimeUnavailable) as exc:
        load_compiled({"flow": {"compiled": flow}})
    assert exc.value.diagnostic == "flow_not_compiled"
    assert problem in str(exc.value)


def test_another_schema_version_is_not_run() -> None:
    flow = compiled()
    flow["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(FlowRuntimeUnavailable):
        load_compiled({"flow": {"compiled": flow}})


def test_a_section_without_its_values_is_not_run() -> None:
    """The compiler writes every value of a section; the worker has no defaults for them."""
    flow = compiled()
    del flow["nodes"]["n_end00000"]["end"]["reason"]
    with pytest.raises(FlowRuntimeUnavailable):
        load_compiled({"flow": {"compiled": flow}})
