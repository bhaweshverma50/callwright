"""End-call tool (005 T026): let the reply that called it finish playing, speak the configured
goodbye unless the reply already said something (its own goodbye, or the goodbye filler said
when the model ended the call without words), then hang up with ``agent_hangup``. Hanging up
stops speech at once, so without the wait the goodbye would be cut off."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from worker.tools.base import ToolContext, ToolResult, ToolSpecView


class EndCallExecutor:
    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        if ctx.wait_for_playout is not None:
            with contextlib.suppress(Exception):
                await ctx.wait_for_playout()
        message = str(arguments.get("goodbye") or spec.config.get("message") or "").strip()
        if message and not ctx.reply_spoke():
            await ctx.speak(message)
        await ctx.control.hang_up("agent_hangup")
        return ToolResult(llm_payload='{"ended":true}', output="ended")
