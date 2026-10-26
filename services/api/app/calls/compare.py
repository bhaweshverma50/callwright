"""Compare two calls (006 T054, FR-016): turn alignment, flow diff and verdict diffs.

A turn starts at each caller message; the agent's greeting and anything before the first caller
message is turn 0. Turn N of the left call lines up with turn N of the right. The flow diff
compares the visited nodes position by position. Verdict diffs come from the quality port and
stay empty until 007 registers it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.calls.quality_port import VerdictDiff


def _turns(items: Sequence[Mapping[str, Any]]) -> dict[int, list[str]]:
    turns: dict[int, list[str]] = {}
    current = 0
    for item in items:
        if item.get("type") == "message" and item.get("role") == "user":
            current += 1
        turns.setdefault(current, []).append(str(item["id"]))
    return turns


def align_turns(
    left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    lt, rt = _turns(left), _turns(right)
    return [
        {"turn_index": i, "left_item_ids": lt.get(i, []), "right_item_ids": rt.get(i, [])}
        for i in sorted(set(lt) | set(rt))
    ]


def flow_diff(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(max(len(left), len(right))):
        a = left[i].get("to_node_id") if i < len(left) else None
        b = right[i].get("to_node_id") if i < len(right) else None
        out.append({"sequence": i + 1, "left_node_id": a, "right_node_id": b, "differs": a != b})
    return out


def verdict_diffs_json(diffs: Sequence[VerdictDiff]) -> list[dict[str, Any]]:
    out = []
    for d in diffs:
        delta = (
            d.right_score - d.left_score if d.left_score is not None and d.right_score is not None else None
        )
        out.append(
            {
                "evaluator_id": d.evaluator_id,
                "evaluator_name": d.evaluator_name,
                "left": {"verdict": d.left_verdict, "score": d.left_score},
                "right": {"verdict": d.right_verdict, "score": d.right_score},
                "score_delta": round(delta, 4) if delta is not None else None,
                "right_rationale": d.right_rationale,
            }
        )
    return out
