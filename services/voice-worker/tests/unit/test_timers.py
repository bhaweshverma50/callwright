"""T049: inactivity and duration timers on a virtual clock (research R9)."""

from __future__ import annotations

from tests.harness.clock import VirtualClock
from worker.call_behavior import DurationTimer, InactivityTimer


def run(clock: VirtualClock, until: float) -> None:
    while clock.fire_next(until):
        pass
    clock.set_time(until)


def test_inactivity_fires_after_timeout() -> None:
    clock = VirtualClock()
    fired: list[float] = []
    timer = InactivityTimer(clock, 10, lambda: fired.append(clock.now()))
    timer.start()
    run(clock, 9.99)
    assert fired == []
    run(clock, 10)
    assert fired == [10]


def test_activity_resets_the_countdown() -> None:
    clock = VirtualClock()
    fired: list[float] = []
    timer = InactivityTimer(clock, 10, lambda: fired.append(clock.now()))
    timer.start()
    run(clock, 6)
    timer.activity()  # caller speech start, agent speech start, keypad digit
    run(clock, 15)
    assert fired == []
    run(clock, 16)
    assert fired == [16]


def test_pending_work_suspends_and_restarts_full_timeout() -> None:
    clock = VirtualClock()
    fired: list[float] = []
    timer = InactivityTimer(clock, 10, lambda: fired.append(clock.now()))
    timer.start()
    timer.busy_begin("agent")  # reply generation or tool run
    timer.busy_begin("tool")
    run(clock, 100)
    assert fired == []
    timer.busy_end("tool")
    run(clock, 200)
    assert fired == []  # still generating
    timer.busy_end("agent")
    run(clock, 209)
    assert fired == []
    run(clock, 210)
    assert fired == [210]


def test_inactivity_fires_once_and_stop_cancels() -> None:
    clock = VirtualClock()
    fired: list[float] = []
    timer = InactivityTimer(clock, 10, lambda: fired.append(clock.now()))
    timer.start()
    run(clock, 10)
    timer.activity()
    run(clock, 30)
    assert fired == [10]
    stopped = InactivityTimer(clock, 10, lambda: fired.append(-1))
    stopped.start()
    stopped.stop()
    run(clock, 100)
    assert -1 not in fired


def test_duration_timer_fires_at_max_duration() -> None:
    clock = VirtualClock()
    fired: list[float] = []
    timer = DurationTimer(clock, 30, lambda: fired.append(clock.now()))
    timer.start()
    run(clock, 29.9)
    assert fired == []
    run(clock, 60)
    assert fired == [30]


def test_simultaneous_fire_first_writer_wins() -> None:
    """Both limits due at the same instant: exactly one disconnect reason is kept."""
    clock = VirtualClock()
    reasons: list[str] = []

    def end(reason: str) -> None:
        if not reasons:
            reasons.append(reason)

    inactivity = InactivityTimer(clock, 30, lambda: end("inactivity"))
    duration = DurationTimer(clock, 30, lambda: end("max_duration_reached"))
    inactivity.start()
    duration.start()
    run(clock, 30)
    assert inactivity.fired and duration.fired
    assert reasons == ["inactivity"]
