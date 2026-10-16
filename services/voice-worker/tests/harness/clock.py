"""Virtual clock for the offline harness (research R20).

Implements ``worker.call_behavior.Clock``. Time only moves when the runner advances it, so
timers, keypad pauses, voicemail waits and every latency value are deterministic.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class VirtualTimer:
    when: float
    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


@dataclass(order=True)
class _Entry:
    when: float
    seq: int
    timer: VirtualTimer = field(compare=False)


class VirtualClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._heap: list[_Entry] = []
        self._seq = 0

    def now(self) -> float:
        return self._now

    def call_later(self, delay_s: float, callback: Callable[[], None]) -> VirtualTimer:
        timer = VirtualTimer(self._now + max(0.0, delay_s), callback)
        self._seq += 1
        heapq.heappush(self._heap, _Entry(timer.when, self._seq, timer))
        return timer

    def call_at(self, when: float, callback: Callable[[], None]) -> VirtualTimer:
        return self.call_later(when - self._now, callback)

    def next_due(self) -> float | None:
        while self._heap and self._heap[0].timer.cancelled:
            heapq.heappop(self._heap)
        return self._heap[0].when if self._heap else None

    def fire_next(self, until: float) -> bool:
        """Fire the earliest timer due at or before ``until``. Returns False when none is."""
        due = self.next_due()
        if due is None or due > until:
            return False
        entry = heapq.heappop(self._heap)
        self._now = max(self._now, entry.when)
        entry.timer.callback()
        return True

    def set_time(self, when: float) -> None:
        self._now = max(self._now, when)
