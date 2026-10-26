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


def test_silence_checks_in_twice_then_ends() -> None:
    clock = VirtualClock()
    events: list[tuple[str, float]] = []
    timer = InactivityTimer(
        clock,
        30,
        lambda: events.append(("end", clock.now())),
        on_check_in=lambda stage: events.append((f"check-in {stage}", clock.now())),
    )
    timer.start()
    run(clock, 10)
    assert events == [("check-in 0", 10)] and timer.checking_in
    # The check-in is spoken for 2 s: the agent is busy, and its speech does not reset the count.
    timer.busy_begin("agent")
    run(clock, 12)
    timer.busy_end("agent")
    run(clock, 22)
    assert events[-1] == ("check-in 1", 22)
    run(clock, 32)
    assert events[-1] == ("end", 32) and timer.fired


def test_caller_speech_after_a_check_in_starts_over() -> None:
    clock = VirtualClock()
    events: list[str] = []
    timer = InactivityTimer(
        clock,
        30,
        lambda: events.append("end"),
        on_check_in=lambda s: events.append(f"check-in {s}"),
    )
    timer.start()
    run(clock, 10)
    timer.activity()  # the caller answers
    assert not timer.checking_in
    run(clock, 19.9)
    assert events == ["check-in 0"]
    run(clock, 20)
    assert events == ["check-in 0", "check-in 0"]


def test_short_silence_window_checks_in_at_a_third() -> None:
    from worker.call_behavior import check_in_gaps

    assert check_in_gaps(12) == (4.0, 4.0, 4.0)
    assert check_in_gaps(30) == (10.0, 10.0, 10.0)
    assert check_in_gaps(70) == (10.0, 30.0, 30.0)
