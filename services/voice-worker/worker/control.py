"""The worker's :class:`~worker.tools.CallControl` implementation.

Tools (005) and flows (004) act on a call only through this object. Side effects that need the
media session (speaking, ending, keypad tones) go to a :class:`CallBackend`: the live LiveKit
call in ``worker.entry`` or the scripted call in the offline harness, so both run the same
control logic (first writer wins on hang-up, event reporting, override staging).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from worker import telemetry
from worker.call_behavior import DTMF_DIGITS
from worker.metrics import EventRecorder
from worker.pipeline import OverrideManager
from worker.tools import OverrideResult, SegmentOverrides, ToolActivity


class CallBackend(Protocol):
    async def speak(self, text: str, allow_interruptions: bool) -> None: ...

    async def end(self, reason: str, diagnostic: str | None) -> None:
        """Stop speech, post the final status, close the session and the room."""
        ...

    async def send_dtmf(self, digits: str) -> None: ...


class RuntimeCallControl:
    def __init__(
        self,
        call_id: str,
        recorder: EventRecorder,
        backend: CallBackend,
        *,
        overrides: OverrideManager | None = None,
        room: Any = None,
        on_overrides_staged: Callable[[], None] | None = None,
    ) -> None:
        self._call_id = call_id
        self._recorder = recorder
        self._backend = backend
        self._overrides = overrides
        self._room = room
        self._on_staged = on_overrides_staged
        self.disconnect_reason: str | None = None
        self.diagnostic: str | None = None

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def room(self) -> Any:
        return self._room

    @property
    def ending(self) -> bool:
        return self.disconnect_reason is not None

    async def hang_up(self, reason: str, *, diagnostic: str | None = None) -> bool:
        """End the call once; later callers get False (first writer wins, data-model 9)."""
        if self.disconnect_reason is not None:
            return False
        self.disconnect_reason = reason
        self.diagnostic = diagnostic
        await self._backend.end(reason, diagnostic)
        return True

    async def say(self, text: str, *, allow_interruptions: bool = True) -> None:
        if self.ending:
            return
        await self._backend.speak(text, allow_interruptions)

    async def send_dtmf(self, digits: str) -> None:
        if not digits or any(d not in DTMF_DIGITS for d in digits):
            raise ValueError(f"invalid keypad digits {digits!r}")
        self._recorder.dtmf(digits, "sent")
        await self._backend.send_dtmf(digits)

    def report_tool(self, activity: ToolActivity) -> None:
        telemetry.record_tool_call(
            activity.name,
            ref=activity.ref,
            is_error=activity.is_error,
            duration_ms=activity.duration_ms,
        )
        self._recorder.tool_call(
            activity.name,
            ref=activity.ref,
            arguments=activity.arguments or None,
            output=activity.output,
            is_error=activity.is_error,
            duration_ms=activity.duration_ms,
            extra=activity.extra or None,
        )
        at = self._recorder.offset_ms()
        call_item: dict[str, Any] = {
            "type": "tool_call",
            "name": activity.name,
            "arguments": activity.arguments,
        }
        # 008 simulations: where the answer came from (mock, recorded, synthesized, error).
        source = (activity.extra or {}).get("answer_source")
        if source:
            call_item["answer_source"] = source
        if activity.ref:
            call_item["ref"] = activity.ref
        if at is not None:
            call_item["at_ms"] = at
        self._recorder.transcript_item(call_item)
        if activity.output is not None:
            result: dict[str, Any] = {
                "type": "tool_result",
                "name": activity.name,
                "output": activity.output[:8192],
                "is_error": activity.is_error,
            }
            if source:
                result["answer_source"] = source
            if activity.ref:
                result["ref"] = activity.ref
            if activity.duration_ms is not None:
                result["duration_ms"] = activity.duration_ms
            self._recorder.transcript_item(result)

    def report_transition(
        self,
        to_node_id: str,
        *,
        from_node_id: str | None = None,
        label: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self._recorder.flow_transition(to_node_id, from_node_id, label, details)
        item: dict[str, Any] = {"type": "flow_transition", "to_node_id": to_node_id}
        if from_node_id:
            item["from_node_id"] = from_node_id
        if label:
            item["label"] = label
        at = self._recorder.offset_ms()
        if at is not None:
            item["at_ms"] = at
        self._recorder.transcript_item(item)

    async def apply_overrides(self, overrides: SegmentOverrides) -> OverrideResult:
        """Stage per-segment overrides (FR-046); they apply at the next turn boundary."""
        if self._overrides is None:
            return OverrideResult(rejected=tuple(k for k, v in overrides.items() if v))
        result = self._overrides.request(overrides)
        if result.pending and self._on_staged is not None:
            self._on_staged()
        return result
