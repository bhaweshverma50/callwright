"""The spec's enums and data-channel messages equal the contract (the web generates its types
and values from the spec fragments, the services import the contract)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

import yaml

from callwright_contract import data_channel
from callwright_contract.calls import (
    ACTIVE_STATUSES,
    CALL_STATUSES,
    CHANNELS,
    DISCONNECT_REASONS,
    STILL_CHANGING_STATUSES,
    SYSTEM_EVENTS,
    ControlReason,
)
from callwright_contract.textsim import SimulationEndReason

SPECS = Path(__file__).resolve().parents[3] / "specs"


def schemas(path: str) -> dict[str, Any]:
    found: dict[str, Any] = yaml.safe_load((SPECS / path).read_text())["components"]["schemas"]
    return found


def test_call_vocabulary() -> None:
    calls = schemas("006-calls-analytics/contracts/calls.yaml")
    status = calls["CallStatus"]
    assert tuple(status["enum"]) == CALL_STATUSES
    assert set(status["x-on-air"]) == ACTIVE_STATUSES
    assert set(status["x-still-changing"]) == STILL_CHANGING_STATUSES
    assert tuple(calls["DisconnectReason"]["enum"]) == DISCONNECT_REASONS
    assert tuple(calls["Channel"]["enum"]) == CHANNELS


def properties(node: Any, name: str) -> list[dict[str, Any]]:
    """Every definition of property ``name`` under ``node`` (through allOf and nesting)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict) and name in node["properties"]:
            found.append(node["properties"][name])
        for value in node.values():
            found += properties(value, name)
    elif isinstance(node, list):
        for value in node:
            found += properties(value, name)
    return found


def test_worker_events() -> None:
    events = schemas("003-voice-runtime/contracts/call_events.yaml")
    (event,) = properties(events["RuntimeTranscriptItem"], "event")
    assert tuple(event["enum"]) == SYSTEM_EVENTS
    reasons = [tuple(p["enum"]) for p in properties(events, "disconnect_reason") if "enum" in p]
    assert DISCONNECT_REASONS in reasons  # the status event takes every reason
    assert get_args(ControlReason) in reasons  # the API's end_call control takes two of them
    assert all(set(r) <= set(DISCONNECT_REASONS) for r in reasons)


def test_simulation_end_reasons() -> None:
    simulator = schemas("008-testing-simulation/contracts/simulator.yaml")
    assert tuple(simulator["SimEndReason"]["enum"]) == get_args(SimulationEndReason)


def test_data_channel_messages() -> None:
    messages = schemas("003-voice-runtime/contracts/data_channel.yaml")
    latency = messages["TurnLatencyMessage"]
    assert latency["x-data-channel"]["topic"] == data_channel.LATENCY_TOPIC
    assert tuple(latency["properties"]) == data_channel.LATENCY_FIELDS
    entered = messages["FlowNodeEnteredMessage"]
    assert entered["x-data-channel"]["topic"] == data_channel.FLOW_TOPIC
    assert tuple(entered["properties"]) == data_channel.NODE_ENTERED_FIELDS
    assert entered["properties"]["type"]["const"] == data_channel.NODE_ENTERED
