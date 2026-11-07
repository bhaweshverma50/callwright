"""Turn-latency benchmark and baseline gate (Principle II, T102 and T103).

Fake mode (default, offline): runs the call set through the harness with vendor delays sampled
from the call set's profiles and reports p50 and p95 ``e2e_ms`` plus component medians. The run
fails when p50 > 800 ms, p95 > 1,500 ms, or either regresses more than 10% against the
baseline. ``--update-baseline`` rewrites the baseline from this run.

Live mode (``--mode live``, :mod:`tests.harness.bench.live`) runs the same call set over real
WebRTC rooms on a LiveKit server (``livekit-server --dev``): a scripted caller publishes the WAV
fixtures, the production agent server and job entry handle the call with fake STT, LLM and TTS
adapters, and ``e2e_ms`` is measured at the caller. It gates on the same budgets against
``baseline_live.json`` and also fails on missed turns, event contract violations, or a cut-off
(the agent speaking before the caller's last sample, research R4).
``--callset bench/callset_pauses.yaml`` runs the mid-sentence pause and digit-group scenarios;
``--vendors real`` runs the real adapters with the worker's vendor keys (``live_real``).

    python -m tests.harness.bench.benchmark
    python -m tests.harness.bench.benchmark --update-baseline
    python -m tests.harness.bench.benchmark --mode live [--calls 4 --concurrency 2]
    python -m tests.harness.bench.benchmark --mode live --callset \
        tests/harness/bench/callset_pauses.yaml
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
from typing import Any, Protocol

import yaml

from tests.harness.bench.synth import Turn
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
    config: Mapping[str, Any],
    turns: Sequence[str | Mapping[str, Any]],
    rng: random.Random,
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    call = HarnessCall(Script(name="bench", steps=[]), dict(config))
    await call.connect()
    for raw in turns:
        turn = Turn.parse(raw)
        call.stt.final_delay_s = sample_ms(rng, profile["stt_final_ms"]) / 1000.0
        call.llm.ttft_s = sample_ms(rng, profile["llm_ttft_ms"]) / 1000.0
        call.tts.ttfb_s = sample_ms(rng, profile["tts_ttfb_ms"]) / 1000.0
        step = Step(say=turn.say, segment_pause_ms=turn.pause_ms)
        await call.caller_says(step, turn.say)
        await call.wait_idle()
    await call.control.hang_up("user_hangup")
    return [e for e in call.events if e["type"] == "turn" and e["turn_index"] > 0]


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


class LatencyReport(Protocol):
    @property
    def e2e_p50_ms(self) -> float: ...

    @property
    def e2e_p95_ms(self) -> float: ...


def gate(
    report: LatencyReport, baseline: Mapping[str, Any] | None, *, p50_budget: bool = True
) -> list[str]:
    """Budget and regression checks. Returns the failures (empty means pass).

    ``p50_budget=False`` is for call sets that are not a representative turn mix (the R4 pause
    scenarios, where most turns end in a digit string and wait the unfinished-turn delay).
    """
    failures: list[str] = []
    if p50_budget and report.e2e_p50_ms > P50_BUDGET_MS:
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
    parser.add_argument("--url", default="ws://localhost:7880", help="live: LiveKit server")
    parser.add_argument("--api-key", default="devkey", help="live: LiveKit API key")
    parser.add_argument("--api-secret", default="secret", help="live: LiveKit API secret")
    parser.add_argument("--calls", type=int, help="live: number of calls (default: call set)")
    parser.add_argument("--concurrency", type=int, help="live: calls in parallel")
    parser.add_argument("--details", type=Path, help="live: write per-turn numbers (JSON)")
    parser.add_argument(
        "--vendors",
        choices=["fake", "real"],
        default="fake",
        help="live: real vendor adapters (keys from the environment; no baseline gate)",
    )
    args = parser.parse_args(argv)
    if args.mode == "live":
        return run_live_mode(args)
    report = asyncio.run(run_benchmark(args.callset))
    if args.update_baseline:
        args.baseline.write_text(json.dumps(report.to_json(), indent=2) + "\n")
    baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
    failures = gate(report, baseline)
    print(json.dumps({"report": report.to_json(), "failures": failures}, indent=2))
    return 1 if failures else 0


def run_live_mode(args: argparse.Namespace) -> int:
    import logging

    from tests.harness.bench.live import DEFAULT_LIVE_BASELINE, LiveOptions, run_live

    logging.basicConfig(level=logging.WARNING)
    # The live baseline belongs to the default call set; other call sets (the R4 pause
    # scenarios) gate on the budgets and cut-offs unless a baseline is named.
    baseline_path: Path | None = args.baseline
    if args.baseline == DEFAULT_BASELINE:
        default = args.callset.resolve() == DEFAULT_CALLSET.resolve()
        baseline_path = DEFAULT_LIVE_BASELINE if default else None
    options = LiveOptions(
        url=args.url,
        api_key=args.api_key,
        api_secret=args.api_secret,
        calls=args.calls,
        concurrency=args.concurrency,
        vendors=args.vendors,
    )
    if args.vendors == "real":
        baseline_path = None  # vendor latency varies; real runs report, the fake run gates
    report = asyncio.run(run_live(args.callset, options))
    callset = yaml.safe_load(args.callset.read_text())
    p50_budget = bool((callset.get("gate") or {}).get("p50", True))
    if args.details:
        args.details.write_text(json.dumps(report.details, indent=2) + "\n")
    if args.update_baseline and baseline_path is not None:
        baseline_path.write_text(json.dumps(report.to_json(), indent=2) + "\n")
    baseline = (
        json.loads(baseline_path.read_text())
        if baseline_path is not None and baseline_path.exists()
        else None
    )
    failures = gate(report, baseline, p50_budget=p50_budget)
    if report.cutoffs:
        failures.append(f"{report.cutoffs} caller turns were cut off mid-sentence")
    if report.missed_turns:
        failures.append(f"{report.missed_turns} caller turns got no agent audio")
    if report.contract_violations:
        failures.append(f"{report.contract_violations} event contract violations")
    print(json.dumps({"report": report.to_json(), "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
