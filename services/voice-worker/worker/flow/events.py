"""Flow move records and live node announcements (T056; data-model section 6, research R14).

Every move becomes a ``flow_transition`` CallEvent through ``CallControl.report_transition``
with the full payload (labels, trigger, turn, timing, variables set). Node entries are announced
on the LiveKit data channel, topic ``callwright.flow``, so the builder highlights the active
node during a test call (FR-033).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from worker.tools import CallControl

log = logging.getLogger(__name__)
TOPIC = "callwright.flow"
Publisher = Callable[[bytes], Awaitable[None]]


@dataclass
class FlowEvents:
    control: CallControl | None
    offset_ms: Callable[[], int | None] = lambda: None
    publish: Publisher | None = None
    turn_index: Callable[[], int] = lambda: 0
    started: float = field(default_factory=time.monotonic)
    pending: set[Any] = field(default_factory=set)

    def now_ms(self) -> int:
        offset = self.offset_ms()
        return (
            int(offset) if offset is not None else round((time.monotonic() - self.started) * 1000)
        )

    def move(
        self,
        source: Mapping[str, Any] | None,
        source_id: str | None,
        target: Mapping[str, Any],
        target_id: str,
        *,
        trigger: str,
        edge_id: str | None,
        edge_label: str | None,
        function_name: str | None = None,
        engine_ms: int = 0,
        model_ms: int | None = None,
        variables: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "from_label": (source or {}).get("label") or source_id,
            "to_label": target.get("label") or target_id,
            "edge_id": edge_id,
            "edge_label": edge_label,
            "trigger": trigger,
            "function_name": function_name,
            "turn_index": self.turn_index(),
            "t_ms": self.now_ms(),
            "engine_ms": engine_ms,
            "model_ms": model_ms,
            "to_node_type": target.get("type"),
        }
        if variables:
            details["variables"] = dict(variables)
        if note:
            details["note"] = note
        details = {k: v for k, v in details.items() if v is not None}
        if self.control is not None:
            try:
                self.control.report_transition(
                    target_id, from_node_id=source_id, label=edge_label, details=details
                )
            except Exception:  # recording must never break the call
                log.exception("could not record flow move to %s", target_id)
        self.announce(target_id)
        return details

    def announce(self, node_id: str) -> None:
        if self.publish is None:
            return
        data = json.dumps(
            {"type": "node_entered", "node_id": node_id, "at_ms": self.now_ms()}
        ).encode()
        import asyncio

        async def send() -> None:
            assert self.publish is not None
            try:
                await self.publish(data)
            except Exception as exc:  # best effort, like the latency panel
                log.debug("flow node announcement failed: %s", exc)

        try:
            task = asyncio.get_running_loop().create_task(send())
        except RuntimeError:
            return
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
