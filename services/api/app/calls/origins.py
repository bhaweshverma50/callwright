"""What a call's origin allows (contract ``Origin``): every rule that treats simulated calls
differently reads this table.

* ``billable``: charged as call minutes, so the balance is checked at admission, the credit guard
  runs mid-call and the pipeline prices the call. Simulations are billed as feature charges (008).
* ``holds_slot``: counts against the workspace's concurrent-call limit.
* ``reaches_customer``: customer webhooks are sent and callbacks are really booked (008 FR-018).
* ``saves_preferences``: the caller's language is saved for their number (012).
* ``has_real_audio``: a conversation on the voice runtime, with real call time, audio, latency
  and vendor keys. Simulations are text runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

Origin = Literal["live", "test", "simulation"]
ORIGINS: Final[tuple[Origin, ...]] = get_args(Origin)


@dataclass(frozen=True)
class OriginPolicy:
    billable: bool
    holds_slot: bool
    reaches_customer: bool
    saves_preferences: bool
    has_real_audio: bool


_REAL = OriginPolicy(
    billable=True, holds_slot=True, reaches_customer=True, saves_preferences=True, has_real_audio=True
)
POLICIES: Final[dict[str, OriginPolicy]] = {
    "live": _REAL,
    "test": _REAL,
    "simulation": OriginPolicy(
        billable=False,
        holds_slot=False,
        reaches_customer=False,
        saves_preferences=False,
        has_real_audio=False,
    ),
}
SLOT_ORIGINS: Final = tuple(o for o in ORIGINS if POLICIES[o].holds_slot)


def policy(origin: str) -> OriginPolicy:
    return POLICIES[origin]
