"""Built-in ``set_language`` tool (012).

Single-prompt agents get it when the claim offers more than one language
(``RuntimeConfig.language_options``, the agent's own first). The model calls it when the caller
asks to switch or clearly speaks another listed language. For the rest of the call:

* speech recognition: the option's model and language, staged through the segment override
  path (``OverrideManager``) and swapped in at the next turn boundary, so the caller's next
  sentence is heard in the new language;
* replies: the agent's instructions get "reply only in <language>" at once (the reply that
  called the tool confirms the switch in the new language), and every rebuilt agent keeps it;
* voice: the option's model with the language. Multilingual voices (the default Multilingual
  v2, Flash and Turbo v2.5) speak whatever language the text is in; an English-only model
  (Flash v2, Turbo v2) is replaced for the rest of the call by its multilingual version (same
  price), which the API names in the option. Like speech recognition, the voice model changes
  at the next turn boundary, so with an English-only model the one-sentence confirmation is
  still spoken by the old model.

The switch is recorded as a ``tool_call`` event and a ``language_switched`` system item, and
reported to ``POST /v1/internal/calls/{id}/language`` in the background, which saves it for the
caller on phone calls. Simulations (008) never report: instructions switch, nothing is stored.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from worker.tools.base import ToolContext, ToolResult, ToolSpecView

log = logging.getLogger(__name__)

TOOL_TYPE = "set_language"
TOOL_NAME = "set_language"
TIMEOUT_S = 5.0
DESCRIPTION = (
    "Switch the call to another language when the caller asks for it or clearly speaks it. "
    "Speech recognition, your replies and your voice change for the rest of the call."
)


def _get(option: Any, key: str) -> Any:
    return option.get(key) if isinstance(option, Mapping) else getattr(option, key, None)


def parameters(options: Sequence[Any]) -> dict[str, Any]:
    codes = [str(_get(o, "code")) for o in options]
    names = "; ".join(f"{_get(o, 'code')} = {_get(o, 'label')}" for o in options)
    return {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "enum": codes,
                "description": f"The language to speak from now on: {names}.",
            }
        },
        "required": ["language"],
    }


def spec_for(options: Sequence[Any]) -> ToolSpecView:
    return ToolSpecView(
        tool_id=None,
        type=TOOL_TYPE,
        name=TOOL_NAME,
        description=DESCRIPTION,
        config={"parameters": parameters(options)},
    )


def _payload(body: dict[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


class SetLanguageExecutor:
    def __init__(
        self,
        options: Sequence[Any],
        current: str | None,
        client: httpx.AsyncClient | None,
        base_url: str,
        service_token: str,
        *,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self.options = {str(_get(o, "code")): o for o in options}
        first = str(_get(options[0], "code")) if options else ""
        self.current = current if current in self.options else first
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {service_token}"}
        self.timeout_s = timeout_s
        self.reports: set[asyncio.Task[None]] = set()

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        code = str(arguments.get("language") or "")
        option = self.options.get(code)
        if option is None:
            return ToolResult.error(
                "unsupported_language",
                "That language is not available on this call. Tell the caller, in the language "
                "you are speaking now, that you cannot switch to it.",
            )
        label = str(_get(option, "label") or code)
        if code == self.current:
            return ToolResult(
                llm_payload=_payload(
                    {
                        "switched": False,
                        "language": code,
                        "message": f"The call is already in {label}. Carry on in {label}.",
                    }
                )
            )
        previous = self.current
        self.current = code
        stt: dict[str, Any] = {"language": code}
        if _get(option, "stt_model"):
            stt["model"] = _get(option, "stt_model")
        await ctx.control.apply_overrides(
            {
                "switch_language": {
                    "code": code,
                    "label": label,
                    "tts_model": _get(option, "tts_model"),
                },
                "stt": stt,  # type: ignore[typeddict-item]
            }
        )
        if ctx.set_reply_language is not None:
            try:
                await ctx.set_reply_language(label)
            except Exception:  # the rebuilt agent at the turn boundary carries it anyway
                log.exception("could not update instructions on %s", ctx.call_id)
        report = getattr(ctx.control, "report_language", None)
        offset_ms = report(code, label) if callable(report) else None
        if not ctx.simulation:
            task = asyncio.ensure_future(self._report(ctx.call_id, code, offset_ms))
            self.reports.add(task)
            task.add_done_callback(self.reports.discard)
        output = {
            "switched": True,
            "language": code,
            "label": label,
            "from": previous,
            "message": (
                f"Switched to {label}. From now on reply only in {label}: confirm the switch in "
                f"{label} in one short sentence, then continue the conversation."
            ),
        }
        return ToolResult(llm_payload=_payload(output), output=_payload(output))

    async def _report(self, call_id: str, code: str, offset_ms: int | None) -> None:
        if self.client is None or not self.base_url:
            return
        body: dict[str, Any] = {"language": code}
        if offset_ms is not None:
            body["offset_ms"] = offset_ms
        try:
            response = await self.client.post(
                f"{self.base_url}/calls/{call_id}/language",
                json=body,
                headers=self.headers,
                timeout=self.timeout_s,
            )
            if response.status_code != 200:
                log.warning("language report for %s: HTTP %s", call_id, response.status_code)
        except httpx.HTTPError as exc:
            log.warning("language report for %s failed: %s", call_id, exc)
