"""HTTP tool executor on calls (005 T047, research R4 to R7).

The request is built by ``http_core`` (shared vectors with the API), sent to the vetted address
with one keep-alive client per call, never retried, and read up to 64 KB. Mapped response values
go into the call's variable store for later tools. When the request is still running after
400 ms and nothing was said yet in this reply, the waiting line is spoken once without entering
the LLM context; the agent's spoken filler (pipeline ``llm_node``) usually covers it first.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

import httpx

from worker.tools import guard, http_core
from worker.tools.base import ToolContext, ToolResult, ToolSpecView

WAITING_LINE_AFTER_S = 0.4
MAX_REDIRECTS = 3
REDIRECTS = frozenset({301, 302, 303, 307, 308})


class HttpExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        allow_http: bool = False,
        resolver: guard.Resolver | None = None,
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
            return ToolResult.error("secret_unavailable", "A credential for this tool is missing.")
        if missing:
            return ToolResult.error("missing_variable", f"No value for {', '.join(missing)}.")
        spoke = False

        async def waiting_line() -> None:
            nonlocal spoke
            await asyncio.sleep(self.waiting_after_s)
            if ctx.reply_spoke():
                return
            spoke = True
            await ctx.speak(str(config.get("execution_message") or "One moment."))

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
        timeout_s = int(config.get("timeout_ms") or 8000) / 1000
        deadline = time.perf_counter() + timeout_s
        method, url, content = prepared.method, prepared.url, prepared.content()
        try:
            for hop in range(MAX_REDIRECTS + 1):
                target = await guard.check(url, allow_http=self.allow_http, resolver=self.resolver)
                headers = {**prepared.headers, "Host": target.host_header()}
                remaining = max(0.05, deadline - time.perf_counter())
                extensions: dict[str, Any] = {"timeout": httpx.Timeout(remaining).as_dict()}
                if target.scheme == "https":
                    extensions["sni_hostname"] = target.host
                request = self.client.build_request(
                    method,
                    target.pinned_url(),
                    content=content,
                    headers=headers,
                    extensions=extensions,
                )
                response = await asyncio.wait_for(
                    self.client.send(request, stream=True, follow_redirects=False), remaining
                )
                location = response.headers.get("location")
                if response.status_code in REDIRECTS and location and hop < MAX_REDIRECTS:
                    await response.aclose()
                    url = urljoin(url, location)
                    if response.status_code == 303 or (
                        response.status_code in (301, 302) and method not in ("GET", "DELETE")
                    ):
                        method, content = "GET", None
                    continue
                try:
                    body, too_large = await asyncio.wait_for(
                        _read_capped(response), max(0.05, deadline - time.perf_counter())
                    )
                finally:
                    await response.aclose()
                break
        except guard.Blocked as exc:
            code = (
                "blocked_address"
                if exc.reason in ("private_address", "https_required")
                else ("connection_error")
            )
            return ToolResult.error(code, "The request could not be sent.")
        except (TimeoutError, httpx.TimeoutException):
            return ToolResult.error("timeout", f"No answer within {timeout_s:g} seconds.")
        except httpx.HTTPError:
            return ToolResult.error("connection_error", "The service could not be reached.")
        status = response.status_code
        text = body.decode("utf-8", errors="replace")
        if too_large:
            return ToolResult.error(
                "response_too_large", "The answer was too large.", http_status=status
            )
        if status >= 400:
            message = f"The service answered HTTP {status}."
            result = ToolResult.error("http_status", message, http_status=status)
            result.output = http_core.truncate(text)
            return result
        mapped, missing = http_core.apply_mappings(
            text, list(config.get("response_mappings") or [])
        )
        payload = http_core.success_payload(text)
        return ToolResult(
            llm_payload=payload,
            output=payload,
            extra={"http_status": status, "mapped_variables": mapped, "missing_paths": missing},
        )


async def _read_capped(response: httpx.Response) -> tuple[bytes, bool]:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > http_core.MAX_RESPONSE_BYTES:
            return bytes(data[: http_core.MAX_RESPONSE_BYTES]), True
    return bytes(data), False
