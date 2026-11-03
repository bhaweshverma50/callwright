"""Flow engine overhead benchmark (004 T051, SC-004, Principle II).

Times the executor alone (move recording, rule evaluation, templating, handler dispatch) with
stubbed services that answer at once, over 500 runs of the clinic-shaped chain
Triage -> Extract -> Rule -> Say -> End, and gates the p95 per move at 150 ms (model time is
not counted; the stubs take none). ``uv run python -m tests.harness.bench.bench_flow_engine``
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
import time
from collections.abc import Mapping
from typing import Any

from tests.flow_support import compiled_config
from tests.harness.bench.benchmark import percentile
from worker.flow import nodes  # noqa: F401  (registers the handlers)
from worker.flow.events import FlowEvents
from worker.flow.executor import FlowRun, WebhookResult
from worker.flow.registry import Move

GATE_P95_MS = 150.0


class InstantServices:
    async def say(self, text: str, *, allow_interruptions: bool = True) -> None:
        return None

    async def classify(self, instructions: str, categories: list[Mapping[str, Any]]) -> str | None:
        return str(categories[0]["name"])

    async def extract(self, instructions: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        return {"age": 21}

    async def webhook(
        self,
        node_id: str,
        request: Mapping[str, Any],
        mock: str | None,
        variables: Mapping[str, Any],
    ) -> WebhookResult:
        return WebhookResult(ok=True)

    async def transfer(self, node_id: str, spec: Mapping[str, Any]) -> bool:
        return True

    async def end(self, message: str, reason: str, *, generate: bool = False) -> None:
        return None

    async def hang_up(self, reason: str, diagnostic: str | None = None) -> None:
        return None


async def run(iterations: int = 500) -> dict[str, float]:
    compiled = copy.deepcopy(compiled_config("rule_else")["flow"]["compiled"])
    per_move: list[float] = []
    for _ in range(iterations):
        flow = FlowRun(compiled, InstantServices(), FlowEvents(None))
        started = time.perf_counter()
        await flow.advance("n_triage00", Move(target="n_extract0", trigger="llm_condition"))
        elapsed = (time.perf_counter() - started) * 1000
        per_move.append(elapsed / max(1, flow.state.transition_count))
    return {
        "runs": float(iterations),
        "p50_ms": round(percentile(per_move, 50), 3),
        "p95_ms": round(percentile(per_move, 95), 3),
        "max_ms": round(max(per_move), 3),
    }


def gate(report: Mapping[str, float]) -> list[str]:
    return (
        [f"engine p95 {report['p95_ms']} ms > {GATE_P95_MS} ms"]
        if report["p95_ms"] > GATE_P95_MS
        else []
    )


def main() -> int:
    report = asyncio.run(run())
    print(json.dumps(report, indent=2))
    return 1 if gate(report) else 0


if __name__ == "__main__":
    sys.exit(main())
