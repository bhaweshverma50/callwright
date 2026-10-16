"""Offline harness scenarios (T027, T049, T062, T095, T117). No network, no keys."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.runner import SCRIPTS_DIR, HarnessResult, run_script

SCRIPTS = sorted(SCRIPTS_DIR.glob("*.yaml"))


@pytest.mark.parametrize("script", SCRIPTS, ids=[p.stem for p in SCRIPTS])
async def test_script(script: Path) -> None:
    result = await run_script(script)
    assert result.violations == [], result.violations
    assert result.failures == [], "\n".join(result.failures)
    assert result.end_reason is not None
    statuses = [e["status"] for e in result.posted if e["type"] == "status"]
    assert statuses[0] == "in_progress" and statuses[-1] == "ended"


def _reply_waits(result: HarnessResult) -> list[int]:
    return [t["e2e_ms"] for t in result.turns if t["turn_index"] > 0]


async def test_responsiveness_lower_waits_longer() -> None:
    script = SCRIPTS_DIR / "responsiveness.yaml"
    slow = await run_script(script, config_overrides={"call_behavior": {"responsiveness": 0.2}})
    fast = await run_script(script, config_overrides={"call_behavior": {"responsiveness": 0.9}})
    assert slow.ok and fast.ok
    for slow_ms, fast_ms in zip(_reply_waits(slow), _reply_waits(fast), strict=True):
        assert slow_ms > fast_ms


async def test_unfinished_utterance_waits_for_max_delay() -> None:
    """The semantic detector holds an unfinished sentence until the max endpointing delay."""
    finished = await run_script(SCRIPTS_DIR / "responsiveness.yaml")
    from tests.harness.script_schema import Script, Step

    script = Script(name="unfinished", steps=[Step(say="I would like to book a table for")])
    unfinished = await run_script(script)
    assert _reply_waits(unfinished)[0] > _reply_waits(finished)[0] + 1000


async def test_stt_turn_detection_uses_min_delay_only() -> None:
    """Flux has built-in end of turn: only min_endpointing_delay applies (R4, R5)."""
    from tests.harness.script_schema import Script, Step

    script = Script(name="flux", steps=[Step(say="I would like to book a table for")])
    result = await run_script(script, config_overrides={"stt": {"model": "flux-general-en"}})
    assert result.plan.turn_detection == "stt"
    assert _reply_waits(result)[0] < 1000


async def test_greeting_latency_recorded_as_turn_zero() -> None:
    result = await run_script(SCRIPTS_DIR / "greeting.yaml")
    greeting = next(t for t in result.turns if t["turn_index"] == 0)
    assert greeting["e2e_ms"] == greeting["tts_ttfb_ms"] == 120


async def test_usage_snapshots_are_cumulative_and_monotonic() -> None:
    result = await run_script(SCRIPTS_DIR / "segment_override.yaml")
    snapshots = [e["usage"] for e in result.posted if e["type"] == "usage"]
    assert len(snapshots) >= 2
    seen: dict[tuple[str, str, str, str], int] = {}
    for snap in snapshots:
        for comp, rows in snap.items():
            for row in rows:
                for key, value in row.items():
                    if isinstance(value, int):
                        ident = (comp, row["provider"], str(row.get("model")), key)
                        assert value >= seen.get(ident, 0)
                        seen[ident] = value


async def test_heartbeat_posts_at_least_every_interval() -> None:
    result = await run_script(SCRIPTS_DIR / "credit_guard.yaml")
    # Two heartbeats at 10 s and 20 s; the second carries end_call.
    assert result.end_reason == "insufficient_credit"
    assert 20.0 <= result.duration_s < 21.0
