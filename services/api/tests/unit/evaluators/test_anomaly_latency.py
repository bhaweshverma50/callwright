"""``anomaly_detection`` with fixed neighbour distances and ``latency_slo`` (007 T078)."""

from __future__ import annotations

from typing import Any

from app.evals.embeddings import Neighbours, call_text
from app.evaluators.builtins.anomaly_detection import AnomalyDetection
from app.evaluators.builtins.latency_slo import LatencySlo
from tests.unit.evaluators.helpers import context, messages, tools

SETTINGS = {"threshold": 0.7, "window_days": 30, "min_sample_size": 30, "knn_k": 10, "backfill_per_run": 5}
CALL = messages(("agent", "Hi"), ("user", "Order status?"), ("agent", "Shipped."))


def finder(distances: list[float], comparable: int) -> Any:
    seen: list[dict[str, Any]] = []

    async def find(ctx: Any, settings: Any) -> Neighbours:
        seen.append(dict(settings))
        return Neighbours(distances, comparable)

    find.seen = seen  # type: ignore[attr-defined]
    return find


async def test_threshold_boundary() -> None:
    a = AnomalyDetection()
    at = await a.evaluate(context(msgs=CALL), SETTINGS, tools(neighbours=finder([0.7] * 10, 40)))
    assert at.items[0].verdict == "pass" and at.items[0].score == 0.7
    above = await a.evaluate(context(msgs=CALL), SETTINGS, tools(neighbours=finder([0.71] * 10, 40)))
    assert above.items[0].verdict == "fail" and "above" in above.items[0].rationale


async def test_insufficient_data_is_not_applicable() -> None:
    out = await AnomalyDetection().evaluate(context(msgs=CALL), SETTINGS, tools(neighbours=finder([0.9], 29)))
    assert out.items[0].verdict == "not_applicable"
    assert out.items[0].rationale == "insufficient data (29 of 30 comparable calls)"


async def test_settings_reach_the_neighbour_search() -> None:
    find = finder([0.2] * 3, 30)
    await AnomalyDetection().evaluate(context(msgs=CALL), {**SETTINGS, "knn_k": 3}, tools(neighbours=find))
    assert find.seen[0]["knn_k"] == 3 and find.seen[0]["window_days"] == 30


def test_call_text_is_normalised() -> None:
    text = call_text(messages(("agent", "Hi   there"), ("user", "Hello")), [], "user_hangup")
    assert text == "agent: Hi there\ncaller: Hello\nended: user_hangup"


async def test_latency_item_per_turn_and_simulated_na() -> None:
    out = await LatencySlo().evaluate(context(latencies=[100, 3500]), {"threshold_ms": 3000}, tools())
    assert [(i.turn_index, i.verdict, i.score) for i in out.items] == [
        (1, "pass", 100.0),
        (2, "fail", 3500.0),
    ]
    sim = await LatencySlo().evaluate(
        context(latencies=[100], origin="simulation"), {"threshold_ms": 3000}, tools()
    )
    assert sim.items[0].verdict == "not_applicable" and sim.items[0].rationale == "no audio timing"
