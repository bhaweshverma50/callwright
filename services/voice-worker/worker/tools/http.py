"""HTTP tool executor on calls (005 T047, research R4 to R7).

The request is built and sent by the contract's ``http_core`` (shared with the API's editor test
runs) with one keep-alive client per call: checked by the URL guard, never retried, read up to
64 KB. Mapped response values go into the call's variable store for later tools. When the
request is still running after 400 ms and nothing was said yet in this reply, the waiting line
is spoken once without entering the LLM context; the agent's spoken filler (pipeline
``llm_node``) usually covers it first.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from typing import Any

import httpx
from callwright_contract import http_core, url_guard
from callwright_contract.values import DEFAULT_EXECUTION_MESSAGE

from worker.tools.base import ToolContext, ToolResult, ToolSpecView

WAITING_LINE_AFTER_S = 0.4


class HttpExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        allow_http: bool = False,
        resolver: url_guard.Resolver | None = None,
        waiting_after_s: float = WAITING_LINE_AFTER_S,
    ) -> None:
        self.client = client
        self.allow_http = allow_http
        self.resolver = resolver
        self.waiting_after_s = waiting_after_s

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        config = spec.config
        prepared = http_core.prepare_request(
            config, arguments, ctx.dynamic_variables, ctx.mapped_variables, ctx.secrets
        )
        missing = prepared.missing_variables
        if any(m.startswith("secret:") for m in missing):
            return ToolResult.error("secret_unavailable", http_core.SECRET_MISSING)
        if missing:
            return ToolResult.error("missing_variable", http_core.missing_message(missing))
        spoke = False

        async def waiting_line() -> None:
            nonlocal spoke
            await asyncio.sleep(self.waiting_after_s)
            if ctx.reply_spoke():
                return
            spoke = True
            await ctx.speak(str(config.get("execution_message") or DEFAULT_EXECUTION_MESSAGE))

        waiter = (
            asyncio.create_task(waiting_line())
            if config.get("speak_during_execution", True)
            else None
        )
        try:
            result = await self._send(prepared, config)
        finally:
            if waiter is not None and not waiter.done():
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter
        result.extra["spoke_execution_message"] = spoke
        if not result.is_error:
            ctx.mapped_variables.update(result.extra.get("mapped_variables") or {})
        result.llm_payload = http_core.scrub(result.llm_payload, prepared.secret_values)
        if result.output is not None:
            result.output = http_core.scrub(result.output, prepared.secret_values)
        return result

    async def _send(
        self, prepared: http_core.PreparedRequest, config: Mapping[str, Any]
    ) -> ToolResult:
        outcome = await http_core.execute(
            self.client,
            prepared,
            http_core.timeout_s(config),
            allow_http=self.allow_http,
            resolver=self.resolver,
        )
        text = outcome.body_text or ""
        if outcome.error_code is not None:
            status = {} if outcome.http_status is None else {"http_status": outcome.http_status}
            result = ToolResult.error(outcome.error_code, outcome.message, **status)
            if outcome.error_code == "http_status":
                result.output = http_core.truncate(text)
            return result
        mapped, missing = http_core.apply_mappings(
            text, list(config.get("response_mappings") or [])
        )
        payload = outcome.llm_payload()
        return ToolResult(
            llm_payload=payload,
            output=payload,
            extra={
                "http_status": outcome.http_status,
                "mapped_variables": mapped,
                "missing_paths": missing,
            },
        )
