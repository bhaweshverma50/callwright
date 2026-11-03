"""End-call tool (005 T026): let the reply that called it finish playing, speak the configured
goodbye unless the reply already said something (its own goodbye, or the goodbye filler said
when the model ended the call without words), then hang up with ``agent_hangup``. Hanging up
stops speech at once, so without the wait the goodbye would be cut off.

The call is not ended while the caller is still talking: speech recognition can finish "I'm
getting a call." as a turn of its own while the caller goes on "Can you call me in five
minutes?", and the model may answer the fragment with a goodbye. The caller's next turn then
gets a reply instead of a hang-up (``CallControl.caller_quiet``)."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from worker.tools.base import ToolContext, ToolResult, ToolSpecView

NOT_ENDED = (
    '{"ended":false,"message":"The caller kept talking, so the call was not ended. Listen to '
    'what they say and answer it."}'
)


class EndCallExecutor:
    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        if ctx.wait_for_playout is not None:
            with contextlib.suppress(Exception):
                await ctx.wait_for_playout()
        quiet = getattr(ctx.control, "caller_quiet", None)
        if callable(quiet) and not await quiet():
            return ToolResult(
                llm_payload=NOT_ENDED,
                output="not ended: the caller is still talking",
                extra={"not_ended": "caller_talking"},
            )
        message = str(arguments.get("goodbye") or spec.config.get("message") or "").strip()
        if message and not ctx.reply_spoke():
            await ctx.speak(message)
        await ctx.control.hang_up("agent_hangup")
        return ToolResult(llm_payload='{"ended":true}', output="ended")
