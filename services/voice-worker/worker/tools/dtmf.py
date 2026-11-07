"""Press-digit tool (005 T028, research R9).

Waits ``delay_ms`` before pressing, then sends each digit through the call control (RFC 4733
events, 100 ms apart). A press that comes sooner than ``cooldown_ms`` after the previous one is
delayed until the cooldown has passed, never dropped. SIP calls only.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from callwright_contract.values import CHANNEL_UNSUPPORTED, MAX_PRESS_DIGITS, PRESS_DIGITS_PATTERN

from worker.tools.base import ToolContext, ToolResult, ToolSpecView

DIGITS = re.compile(PRESS_DIGITS_PATTERN)
Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class PressDigitExecutor:
    def __init__(self, *, clock: Clock = time.monotonic, sleep: Sleep = asyncio.sleep) -> None:
        self.clock = clock
        self.sleep = sleep
        self._last_press: float | None = None
        self._lock = asyncio.Lock()

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        digits = str(arguments.get("digits") or "")
        if not DIGITS.match(digits):
            return ToolResult.error(
                "invalid_arguments", f"Digits must be 0-9, * or #, up to {MAX_PRESS_DIGITS}."
            )
        if not ctx.is_sip and not ctx.simulation:
            return ToolResult.error(CHANNEL_UNSUPPORTED, "Keypad tones need a phone call.")
        if ctx.simulation:
            return ToolResult(llm_payload=f'{{"sent":"{digits}"}}', output=digits, mocked=True)
        delay = int(spec.config.get("delay_ms", 1000)) / 1000
        cooldown = int(spec.config.get("cooldown_ms", 5000)) / 1000
        async with self._lock:
            wait = delay
            if self._last_press is not None:
                wait = max(wait, cooldown - (self.clock() - self._last_press))
            if wait > 0:
                await self.sleep(wait)
            await ctx.control.send_dtmf(digits)
            self._last_press = self.clock()
        return ToolResult(llm_payload=f'{{"sent":"{digits}"}}', output=digits)
