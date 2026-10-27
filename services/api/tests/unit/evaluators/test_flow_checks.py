"""Flow checks (007 T077, FR-043): completion, dead ends, loops and transition judging."""

from __future__ import annotations

import json
from typing import Any

from app.evals.scoring import ItemOutcome, run_verdict
from app.evaluators.base import EvalOutcome
from app.evaluators.builtins.flow_completion import FlowCompletion
from app.evaluators.builtins.node_dead_end import NodeDeadEnd
from app.evaluators.builtins.stuck_loop_detector import StuckLoopDetector
from app.evaluators.builtins.transition_correctness import TransitionCorrectness
from tests.fakes.fake_llm import FakeLlm
from tests.unit.evaluators.helpers import context, flow_config, judge_json, messages, tools

CALL = messages(("agent", "Hi"), ("user", "I want to book"), ("agent", "Sure"))


def ctx(path: list[str], **kw: Any) -> Any:
    return context(msgs=CALL, path=path, config=flow_config(), agent_type="flow", **kw)


def overall(out: EvalOutcome) -> str:
    return run_verdict([ItemOutcome(i.verdict, i.score) for i in out.items])[0]


async def test_flow_completion_end_and_transfer() -> None:
    out = await FlowCompletion().evaluate(ctx(["start", "greet", "book", "end"]), {}, tools())
    assert overall(out) == "pass" and out.items[0].flow_node_label == "Goodbye"
    nodes = dict(flow_config()["flow"]["compiled"]["nodes"])
    nodes["greet"] = {**nodes["greet"], "transitions": [{"target_node_id": "xfer"}]}
    out = await FlowCompletion().evaluate(ctx(["start", "greet", "xfer"]), {}, tools())
    assert overall(out) == "pass" and "transfer" in out.items[0].rationale
    out = await FlowCompletion().evaluate(ctx(["start", "greet", "book"]), {}, tools())
    assert overall(out) == "fail" and out.items[0].flow_node_id == "book"


async def test_node_dead_end_item_per_node() -> None:
    out = await NodeDeadEnd().evaluate(ctx(["start", "greet", "faq", "greet", "book"]), {}, tools())
    assert [(i.flow_node_id, i.verdict) for i in out.items] == [
        ("start", "pass"),
        ("greet", "pass"),
        ("faq", "pass"),
        ("book", "fail"),
    ]
    assert overall(out) == "fail" and "Book slot" in (out.rationale or "")
    out = await NodeDeadEnd().evaluate(ctx(["start", "greet", "end"]), {}, tools())
    assert overall(out) == "pass"


async def test_stuck_loops_three_pass_four_fail() -> None:
    three = ["start"] + ["greet", "faq"] * 3 + ["end"]
    out = await StuckLoopDetector().evaluate(ctx(three), {"max_visits_per_node": 3}, tools())
    assert overall(out) == "pass"
    four = ["start"] + ["greet", "faq"] * 4 + ["end"]
    out = await StuckLoopDetector().evaluate(ctx(four), {"max_visits_per_node": 3}, tools())
    assert overall(out) == "fail"
    assert {i.flow_node_id for i in out.items if i.verdict == "fail"} == {"greet", "faq"}
    assert "visited 4 times" in (out.rationale or "")


async def test_transition_items_per_source_node_with_seeded_shuffle() -> None:
    llm = FakeLlm(replies=[judge_json(1.0), judge_json(0.0, "Should have answered the question.")])
    path = ["start", "greet", "book", "end"]
    out = await TransitionCorrectness().evaluate(ctx(path), {"judge_model": "openai/gpt-5-mini"}, tools(llm))
    # start and book have one way forward; greet has three alternatives and is judged.
    judged = [i for i in out.items if i.verdict != "not_applicable"]
    assert [(i.flow_node_id, i.verdict) for i in judged] == [("greet", "pass")]
    assert len(llm.calls) == 1 and "ALTERNATIVES" in llm.calls[0]["system"]

    first = FakeLlm(replies=[judge_json(1.0)])
    second = FakeLlm(replies=[judge_json(1.0)])
    a, b = ctx(path), ctx(path)
    a.run_id = b.run_id = "evr_SAME"
    await TransitionCorrectness().evaluate(a, {"judge_model": "m/x"}, tools(first))
    await TransitionCorrectness().evaluate(b, {"judge_model": "m/x"}, tools(second))
    assert first.calls[0]["system"] == second.calls[0]["system"]  # same seed, same order
    listings = set()
    for seed in range(12):
        llm = FakeLlm(replies=[judge_json(1.0)])
        c = ctx(path)
        c.run_id = f"evr_{seed}"
        await TransitionCorrectness().evaluate(c, {"judge_model": "m/x"}, tools(llm))
        listings.add(llm.calls[0]["system"].split("ALTERNATIVES:")[1].split("TAKEN")[0])
    assert len(listings) > 1  # different runs present the alternatives in different orders


async def test_transition_failure_counts() -> None:
    llm = FakeLlm(replies=[judge_json(0.1)])
    out = await TransitionCorrectness().evaluate(ctx(["greet", "faq"]), {"judge_model": "m/x"}, tools(llm))
    assert overall(out) == "fail" and out.input_tokens > 0
    assert json.loads(json.dumps(out.items[0].evidence))["to_node_id"] == "faq"
