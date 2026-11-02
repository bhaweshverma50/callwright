"""Tool answers in text simulations (008 T017, research R4, FR-013).

A simulation never reaches a customer endpoint. ``RuntimeConfig.simulation`` already keeps 005
from building HTTP executors (``build_call_tools``, ``node_tools`` and the flow webhook service
check it), makes transfers and keypad presses report fixed outcomes and lets ``end_call`` and
``transfer`` end the call with ``agent_hangup`` and ``call_transfer``; ``kb_search`` runs for
real against the internal API. This module adds the answer for HTTP tools and webhook nodes,
installed as ``ToolContext.simulated_answer`` (:func:`install`), in this order:

1. the tool's (or webhook node's) ``mock_response``: ``answer_source = mock``;
2. replay mode only: the output of the k-th call to the same tool name in the base call's
   recorded tool outputs (k counts this run's calls to that name): ``recorded``;
3. ``missing_mock_policy = synthesize`` (default): a short JSON stand-in written by a model from
   the tool's description, parameter schema and arguments (metered as ``usage.synth``):
   ``synthesized``;
4. ``missing_mock_policy = error`` (or a failed stand-in): ``{"error":"no_mock_configured"}``:
   ``error``.

Response mappings apply to every successful answer, as for a live response. The source is put
on the tool's event and transcript items (``answer_source``) and counted per run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Literal

from worker.textsim.llm import complete
from worker.tools import http_core
from worker.tools.base import ToolContext, ToolResult, ToolSpecView
from worker.tools.registry import CallTools, function_schema

log = logging.getLogger("callwright.textsim")

NO_MOCK = "no_mock_configured"
SYNTHESIS_FAILED = "synthesis_failed"
Policy = Literal["synthesize", "error"]
Synthesizer = Callable[[ToolSpecView, Mapping[str, Any]], Awaitable[str]]

SYNTH_SYSTEM = (
    "You stand in for an external tool during a test conversation with a voice agent. Reply "
    "with one short JSON object that a successful call to this tool could plausibly return for "
    "these arguments. Keep it small and realistic. Output JSON only, no prose and no code fences."
)


def _recorded_pairs(recorded: Iterable[Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for row in recorded:
        if isinstance(row, tuple):
            out.append((str(row[0]), str(row[1])))
        elif isinstance(row, Mapping):
            out.append((str(row.get("name")), str(row.get("output") or "")))
        else:
            out.append((str(row.name), str(row.output)))
    return out


class SimulatedToolAnswers:
    """The ``simulated_answer`` hook for one simulated conversation."""

    def __init__(
        self,
        *,
        policy: Policy = "synthesize",
        recorded: Iterable[Any] = (),
        replay: bool = False,
        synthesize: Synthesizer | None = None,
    ) -> None:
        self.policy = policy
        self.replay = replay
        self.synthesize = synthesize
        self.recorded: dict[str, list[str]] = {}
        for name, output in _recorded_pairs(recorded):
            self.recorded.setdefault(name, []).append(output)
        self.calls: dict[str, int] = {}
        self.counts: dict[str, int] = {"mock": 0, "recorded": 0, "synthesized": 0, "error": 0}
        self.in_flight = 0

    async def __call__(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        self.in_flight += 1
        try:
            return await self._answer(spec, arguments, ctx)
        finally:
            self.in_flight -= 1

    async def _answer(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        k = self.calls.get(spec.name, 0)
        self.calls[spec.name] = k + 1
        mock = (spec.mock_response or "").strip()
        if mock:
            return self._canned(spec, ctx, mock, "mock")
        if self.replay:
            outputs = self.recorded.get(spec.name) or []
            if k < len(outputs):
                return self._canned(spec, ctx, outputs[k], "recorded")
        if self.policy == "synthesize" and self.synthesize is not None:
            try:
                body = await self.synthesize(spec, arguments)
            except Exception as exc:
                log.warning("tool stand-in for %s failed: %s", spec.name, type(exc).__name__)
                return self._error(SYNTHESIS_FAILED, "The stand-in answer could not be made.")
            return self._canned(spec, ctx, body, "synthesized")
        return self._error(NO_MOCK, None)

    def _canned(self, spec: ToolSpecView, ctx: ToolContext, body: str, source: str) -> ToolResult:
        mapped, _ = http_core.apply_mappings(body, list(spec.config.get("response_mappings") or []))
        ctx.mapped_variables.update(mapped)
        payload = http_core.success_payload(body)
        self.counts[source] += 1
        return ToolResult(
            llm_payload=payload,
            output=payload,
            mocked=True,
            extra={"mapped_variables": mapped, "answer_source": source},
        )

    def _error(self, code: str, message: str | None) -> ToolResult:
        self.counts["error"] += 1
        body: dict[str, str] = {"error": code}
        if message:
            body["message"] = message
        payload = json.dumps(body, separators=(",", ":"))
        return ToolResult(
            llm_payload=payload,
            is_error=True,
            error_code=code,
            output=payload,
            mocked=True,
            extra={"answer_source": "error"},
        )


def install(tools: CallTools, answers: SimulatedToolAnswers) -> CallTools:
    """Answer the call's HTTP tools and webhook nodes with ``answers`` (flow node tool sets copy
    the context, so they share the hook). Refuses tools that hold an HTTP executor."""
    if "http" in tools.executors:
        raise RuntimeError("simulation tools must not hold an HTTP executor")
    tools.ctx.simulation = True
    tools.ctx.simulated_answer = answers
    return tools


def clean_json(text: str) -> str:
    """The model's stand-in as compact JSON: code fences removed; anything that is not JSON is
    wrapped as ``{"result": text}``."""
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body.split("\n", 1)[1] if "\n" in body else body
        body = body.rsplit("```", 1)[0].strip()
    try:
        value = json.loads(body)
    except ValueError:
        value = {"result": body[:2000]}
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def tool_synthesizer(llm_for: Callable[[], Any]) -> Synthesizer:
    """A synthesizer over the model ``llm_for()`` returns (built on first use)."""

    async def synthesize(spec: ToolSpecView, arguments: Mapping[str, Any]) -> str:
        schema = function_schema(spec)
        prompt = (
            f"Tool: {spec.name}\n"
            f"Description: {spec.description or schema['description']}\n"
            f"Parameters schema: {json.dumps(schema['parameters'], sort_keys=True)}\n"
            f"Arguments: {json.dumps(dict(arguments), sort_keys=True, default=str)}"
        )
        result = await complete(llm_for(), SYNTH_SYSTEM, [("user", prompt)])
        return clean_json(result.text)

    return synthesize
