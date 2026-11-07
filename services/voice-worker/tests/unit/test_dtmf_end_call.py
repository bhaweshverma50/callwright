"""Press digit and end call (005 T019)."""

from __future__ import annotations

import json

from tests.unit.tool_support import make, tool
from worker.tools.dtmf import PressDigitExecutor


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def dtmf_tools(clock: Clock, **config: int):  # type: ignore[no-untyped-def]
    executor = PressDigitExecutor(clock=clock, sleep=clock.sleep)
    return make(
        [tool("press_digit", "press", {"delay_ms": 1000, "cooldown_ms": 5000, **config})],
        press_digit=executor,
    )


async def test_digits_pattern() -> None:
    clock = Clock()
    h = dtmf_tools(clock)
    assert (
        json.loads(await h.tools.dispatch("press", {"digits": "12a"}))["error"]
        == "invalid_arguments"
    )
    assert h.backend.tones == []


async def test_delay_then_send() -> None:
    clock = Clock()
    h = dtmf_tools(clock)
    assert json.loads(await h.tools.dispatch("press", {"digits": "1#"})) == {"sent": "1#"}
    assert h.backend.tones == ["1#"] and clock.sleeps == [1.0]


async def test_cooldown_delays_instead_of_dropping() -> None:
    clock = Clock()
    h = dtmf_tools(clock)
    await h.tools.dispatch("press", {"digits": "1"})
    clock.now += 2.0
    await h.tools.dispatch("press", {"digits": "2"})
    assert h.backend.tones == ["1", "2"]
    assert clock.sleeps == [1.0, 3.0], "the second press waits out the 5 s cooldown"


async def test_press_digit_needs_sip() -> None:
    h = make([tool("press_digit", "press")], channel="web")
    assert (
        json.loads(await h.tools.dispatch("press", {"digits": "1"}))["error"]
        == "channel_unsupported"
    )


async def test_end_call_speaks_then_hangs_up() -> None:
    h = make([tool("end_call", "end_call", {"message": "Goodbye!"})], channel="web")
    await h.tools.dispatch("end_call", {})
    assert h.backend.said == ["Goodbye!"] and h.backend.ended == ["agent_hangup"]
    assert h.events()[0]["tool_type"] == "end_call"


async def test_end_call_without_message() -> None:
    h = make([tool("end_call", "end_call")])
    await h.tools.dispatch("end_call", {})
    assert h.backend.said == [] and h.backend.ended == ["agent_hangup"]


async def test_end_call_waits_out_a_caller_who_is_still_talking() -> None:
    """Speech recognition can finish "I'm getting a call." as a turn while the caller goes on
    "Can you call me in five minutes?": end_call does not hang up on them."""
    h = make([tool("end_call", "end_call", {"message": "Goodbye!"})])
    h.backend.quiet = False
    out = json.loads(await h.tools.dispatch("end_call", {}))
    assert out["ended"] is False and "kept talking" in out["message"]
    assert h.backend.ended == [] and h.backend.said == []
    assert h.events()[0]["not_ended"] == "caller_talking"
