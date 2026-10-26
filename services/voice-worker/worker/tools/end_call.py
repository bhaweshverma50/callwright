"""End-call tool (005 T026): speak the configured goodbye, then hang up with ``agent_hangup``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.tools.base import ToolContext, ToolResult, ToolSpecView


class EndCallExecutor:
    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        message = str(spec.config.get("message") or "").strip()
        if message:
            await ctx.speak(message)
        await ctx.control.hang_up("agent_hangup")
        return ToolResult(llm_payload='{"ended":true}', output="ended")
