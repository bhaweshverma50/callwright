"""Benchmark call set with tools and knowledge attached (005 T091, Principle II).

Runs the standard call set twice, without and with an agent that has an end-call, a transfer and
an HTTP tool plus a knowledge base attached, and fails when p50 or p95 turn latency regresses by
more than 5% against ``baseline.json``.
Run: ``uv run python -m tests.harness.bench.bench_call_set_tools``
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from tests.harness.bench.benchmark import (
    DEFAULT_BASELINE,
    DEFAULT_CALLSET,
    BenchReport,
    run_benchmark,
)

TOLERANCE = 0.05
TOOLS: list[dict[str, Any]] = [
    {
        "tool_id": "tool_end",
        "type": "end_call",
        "name": "end_call",
        "description": "End the call",
        "config": {},
    },
    {
        "tool_id": "tool_tr",
        "type": "transfer_call",
        "name": "transfer_to_desk",
        "description": "Transfer to the desk",
        "config": {"routing_type": "static", "number": "+14155550100"},
    },
    {
        "tool_id": "tool_http",
        "type": "http",
        "name": "check_availability",
        "description": "Look up slots",
        "mock_response": '{"slots": []}',
        "config": {"url": "https://api.example.invalid/x", "method": "POST", "headers": []},
    },
]
KNOWLEDGE = {"kb_ids": ["kb_1"], "knowledge": [{"kb_id": "kb_1", "name": "FAQ", "description": ""}]}


async def run() -> tuple[BenchReport, BenchReport]:
    callset = yaml.safe_load(DEFAULT_CALLSET.read_text())
    plain = await run_benchmark()
    overrides = dict(callset.get("config_overrides") or {})
    overrides.update({"tools": TOOLS, **KNOWLEDGE})
    callset["config_overrides"] = overrides
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "callset_tools.yaml"
        path.write_text(yaml.safe_dump(callset))
        with_tools = await run_benchmark(path)
    return plain, with_tools


def gate(with_tools: BenchReport, baseline: dict[str, Any]) -> list[str]:
    problems = []
    for key in ("e2e_p50_ms", "e2e_p95_ms"):
        limit = float(baseline[key]) * (1 + TOLERANCE)
        if getattr(with_tools, key) > limit:
            problems.append(f"{key} {getattr(with_tools, key)} > {limit:.0f} (baseline +5%)")
    return problems


if __name__ == "__main__":
    plain_report, tools_report = asyncio.run(run())
    print(
        json.dumps(
            {"without": plain_report.to_json(), "with_tools": tools_report.to_json()}, indent=2
        )
    )
    sys.exit(1 if gate(tools_report, json.loads(DEFAULT_BASELINE.read_text())) else 0)
