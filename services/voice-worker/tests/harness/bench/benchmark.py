"""Turn-latency benchmark and baseline gate (Principle II, T102 and T103).

Fake mode (default, offline): runs the call set through the harness with vendor delays sampled
from the call set's profiles and reports p50 and p95 ``e2e_ms`` plus component medians. The run
fails when p50 > 800 ms, p95 > 1,500 ms, or either regresses more than 10% against the
baseline. ``--update-baseline`` rewrites the baseline from this run.

Live mode (real vendors against ``livekit-server --dev`` with WAV fixtures) is not part of this
wave; ``--mode live`` exits with status 2.

    python -m tests.harness.bench.benchmark
    python -m tests.harness.bench.benchmark --update-baseline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.harness.runner import DEFAULT_CONFIG, HarnessCall, deep_merge, load_agent_config
from tests.harness.script_schema import Script, Step

BENCH_DIR = Path(__file__).parent
DEFAULT_CALLSET = BENCH_DIR / "callset.yaml"
DEFAULT_BASELINE = BENCH_DIR / "baseline.json"
P50_BUDGET_MS = 800
P95_BUDGET_MS = 1500
MAX_REGRESSION = 0.10
Z95 = 1.6449


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile, q in 0..100."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return float(ordered[rank - 1])


def sample_ms(rng: random.Random, profile: Mapping[str, float]) -> float:
    """Log-normal sample with the given median and p95."""
    median = float(profile["median"])
    sigma = math.log(float(profile["p95"]) / median) / Z95
    return median * math.exp(rng.gauss(0.0, sigma))


@dataclass
class BenchReport:
    calls: int
    turns: int
    e2e_p50_ms: float
    e2e_p95_ms: float
    e2e_max_ms: float
    stt_final_median_ms: float
    eou_delay_median_ms: float
    llm_ttft_median_ms: float
    tts_ttfb_median_ms: float

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


async def run_call(
    config: Mapping[str, Any], turns: Sequence[str], rng: random.Random, profile: Mapping[str, Any]
) -> list[dict[str, Any]]:
    call = HarnessCall(Script(name="bench", steps=[]), dict(config))
    await call.connect()
    for text in turns:
        call.stt.final_delay_s = sample_ms(rng, profile["stt_final_ms"]) / 1000.0
        call.llm.ttft_s = sample_ms(rng, profile["llm_ttft_ms"]) / 1000.0
        call.tts.ttfb_s = sample_ms(rng, profile["tts_ttfb_ms"]) / 1000.0
        await call.caller_says(Step(say=text), text)
        await call.wait_idle()
    await call.control.hang_up("user_hangup")
    return [e for e in call.recorder.history if e["type"] == "turn" and e["turn_index"] > 0]


async def run_benchmark(callset_path: Path = DEFAULT_CALLSET) -> BenchReport:
    callset = yaml.safe_load(callset_path.read_text())
    config = deep_merge(load_agent_config(DEFAULT_CONFIG), callset.get("config_overrides") or {})
    rng = random.Random(int(callset.get("seed", 0)))
    turns: list[dict[str, Any]] = []
    for _ in range(int(callset["calls"])):
        turns += await run_call(config, callset["turns"], rng, callset["profile"])

    def med(key: str) -> float:
        return float(statistics.median(t[key] for t in turns if t[key] is not None))

    e2e = [float(t["e2e_ms"]) for t in turns]
    return BenchReport(
        calls=int(callset["calls"]),
        turns=len(turns),
        e2e_p50_ms=percentile(e2e, 50),
        e2e_p95_ms=percentile(e2e, 95),
        e2e_max_ms=max(e2e),
        stt_final_median_ms=med("stt_final_ms"),
        eou_delay_median_ms=med("eou_delay_ms"),
        llm_ttft_median_ms=med("llm_ttft_ms"),
        tts_ttfb_median_ms=med("tts_ttfb_ms"),
    )


def gate(report: BenchReport, baseline: Mapping[str, Any] | None) -> list[str]:
    """Budget and regression checks. Returns the failures (empty means pass)."""
    failures: list[str] = []
    if report.e2e_p50_ms > P50_BUDGET_MS:
        failures.append(f"p50 {report.e2e_p50_ms:.0f} ms > {P50_BUDGET_MS} ms")
    if report.e2e_p95_ms > P95_BUDGET_MS:
        failures.append(f"p95 {report.e2e_p95_ms:.0f} ms > {P95_BUDGET_MS} ms")
    if baseline:
        for key in ("e2e_p50_ms", "e2e_p95_ms"):
            base = float(baseline[key])
            value = float(getattr(report, key))
            if base > 0 and value > base * (1 + MAX_REGRESSION):
                failures.append(
                    f"{key} {value:.0f} ms regressed more than {MAX_REGRESSION:.0%} "
                    f"against baseline {base:.0f} ms"
                )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--callset", type=Path, default=DEFAULT_CALLSET)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "live":
        print("live benchmark (real vendors, livekit-server --dev) is not implemented yet")
        return 2
    report = asyncio.run(run_benchmark(args.callset))
    if args.update_baseline:
        args.baseline.write_text(json.dumps(report.to_json(), indent=2) + "\n")
    baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
    failures = gate(report, baseline)
    print(json.dumps({"report": report.to_json(), "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
