"""Offline harness scenarios (T027, T049, T062, T095, T117). No network, no keys."""

from __future__ import annotations

from pathlib import Path

import pytest
from callwright_contract import diagnostics as diag

from tests.harness.runner import (
    DEFAULT_CONFIG,
    SCRIPTS_DIR,
    HarnessCall,
    HarnessResult,
    load_agent_config,
    run_script,
)
from tests.harness.script_schema import Script, Step

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
    max_ms = unfinished.plan.behavior.endpointing.max_endpointing_delay * 1000
    assert _reply_waits(unfinished)[0] >= max_ms
    assert _reply_waits(unfinished)[0] > _reply_waits(finished)[0] + 500


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


def _paused(name: str, say: str, pause_ms: float) -> Script:
    return Script(name=name, steps=[Step(say=say, segment_pause_ms=pause_ms)])


async def test_pause_longer_than_the_wait_is_a_cut_off() -> None:
    """The boundary of R4: a mid-sentence pause past max_endpointing_delay ends the turn.

    The rest of the sentence then barges in on the reply (interruption sensitivity 0.9), so
    the caller still gets to finish; the scenarios keep their pauses inside the wait.
    """
    say = "I would like to | change my address."
    assert (await run_script(_paused("held", say, 1100))).cutoffs == 0
    result = await run_script(_paused("cut", say, 1400))
    assert result.cutoffs == 1
    users = [t["text"] for t in result.transcript if t["role"] == "user"]
    assert users == ["I would like to", "change my address."]
    assert any(t["interrupted"] for t in result.turns if t["turn_index"] == 1)


async def test_finished_sounding_part_then_pause_is_a_new_turn() -> None:
    """A part that reads as a complete sentence commits after min_endpointing_delay (R4)."""
    result = await run_script(_paused("complete", "I paid. | The rest comes Friday.", 800))
    assert result.cutoffs == 1


async def test_digit_groups_hold_at_the_fastest_responsiveness() -> None:
    """Even at responsiveness 1.0 (max delay 0.9 s) a 700 ms pause between groups holds."""
    result = await run_script(
        SCRIPTS_DIR / "digit_groups.yaml",
        config_overrides={"call_behavior": {"responsiveness": 1.0}},
    )
    assert result.ok, result.failures
    assert result.cutoffs == 0


async def test_vendor_error_hang_up_records_the_vendor_error_line() -> None:
    """The harness ends calls through the worker's own end path, so a vendor failure leaves its
    system line in the transcript."""
    call = HarnessCall(Script(name="vendor_error", steps=[]), load_agent_config(DEFAULT_CONFIG))
    await call.connect()
    diagnostic = diag.diagnostic(diag.VENDOR_ERROR, "tts", "elevenlabs")
    await call.control.hang_up("error", diagnostic=diagnostic)
    await call._drain()
    lines = [e["item"] for e in call.sink.events if e["type"] == "transcript_item"]
    assert [(i["event"], i["detail"]) for i in lines if i["type"] == "system"] == [
        ("vendor_error", diagnostic)
    ]
