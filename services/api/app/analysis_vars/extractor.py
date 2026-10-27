"""Summary, sentiment and typed variable extraction (007 T019; FR-002, FR-003, US1).

The model sees the call inside the same delimited data block as the judges (instructions spoken
in the call are content, never rules: US1 scenario 6) and answers one JSON object. Values are
coerced to each variable's type on the server: a choice outside the fixed set, an unparsable
number or a missing answer is stored as ``None`` ("not found"). Sentiment is ``unknown`` when the
caller never spoke, whatever the model says.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.evaluators.base import Message, ToolEvent
from app.evaluators.judge import PREAMBLE, CompletionClient, Usage, json_object, render_call
from app.llms.adapters.base import ChatMessage, ModelError, ModelTimeout

PURPOSE = "call_analysis"
SENTIMENTS = ("positive", "neutral", "negative", "unknown")
SUMMARY_MAX = 600
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}

INSTRUCTIONS = (
    "Read the call and fill in the analysis. Write a summary of at most 600 characters: why the "
    "caller called and how it ended. Rate the CALLER's sentiment as positive, neutral or "
    "negative. For every variable below, extract the value the call actually contains, using "
    "its description; use null when the call does not contain it. Boolean variables take true "
    "or false, number variables a number, choice variables exactly one of their choices, string "
    "variables a short text."
)


class ExtractionFailed(Exception):
    pass


@dataclass(frozen=True)
class Extraction:
    summary: str
    sentiment: str
    values: dict[str, Any]
    usage: Usage


def output_schema(variables: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """JSON Schema of the reply, built from the active variables (data-model ``call_analyses``)."""
    props: dict[str, Any] = {}
    for v in variables:
        base: Any = {
            "boolean": {"type": "boolean"},
            "number": {"type": "number"},
            "string": {"type": "string", "maxLength": 500},
            "choice": {"type": "string", "enum": list(v.get("choices") or [])},
        }[str(v["type"])]
        props[str(v["name"])] = {"anyOf": [base, {"type": "null"}], "description": v["description"]}
    return {
        "type": "object",
        "required": ["summary", "sentiment", "values"],
        "properties": {
            "summary": {"type": "string", "maxLength": SUMMARY_MAX},
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "values": {"type": "object", "properties": props, "required": list(props)},
        },
    }


def system_prompt(variables: Sequence[Mapping[str, Any]]) -> str:
    spec = [
        {k: v[k] for k in ("name", "type", "description", "choices") if v.get(k) is not None}
        for v in variables
    ]
    return (
        f"{PREAMBLE}\n\nTASK:\n{INSTRUCTIONS}\n\n<variables>\n{json.dumps(spec, ensure_ascii=False)}\n"
        f"</variables>\n\nAnswer with JSON only, matching this schema:\n"
        f"{json.dumps(output_schema(variables), ensure_ascii=False)}"
    )


def coerce(variable: Mapping[str, Any], raw: Any) -> Any:
    """``raw`` as the variable's type, or None (not found)."""
    kind = variable["type"]
    if raw is None:
        return None
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        return True if text in _TRUE else False if text in _FALSE else None
    if kind == "number":
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int | float):
            if not math.isfinite(raw):
                return None
            return int(raw) if isinstance(raw, float) and raw.is_integer() else raw
        text = str(raw).strip().replace(",", ".")
        if not _NUMBER.match(text):
            return None
        number = float(text)
        return int(number) if number.is_integer() and "." not in text else number
    if kind == "choice":
        choices = list(variable.get("choices") or [])
        text = str(raw).strip()
        if text in choices:
            return text
        folded = {c.casefold(): c for c in choices}
        return folded.get(text.casefold())
    text = str(raw).strip() if not isinstance(raw, dict | list) else ""
    return text[:500] or None


def resolve(
    data: Mapping[str, Any], variables: Sequence[Mapping[str, Any]], caller_spoke: bool
) -> tuple[str, str, dict[str, Any]]:
    summary = " ".join(str(data.get("summary") or "").split())[:SUMMARY_MAX]
    sentiment = str(data.get("sentiment") or "").strip().lower()
    if not caller_spoke or sentiment not in SENTIMENTS:
        sentiment = "unknown"
    raw_values = data.get("values")
    raw_values = raw_values if isinstance(raw_values, Mapping) else {}
    values = {str(v["name"]): coerce(v, raw_values.get(str(v["name"]))) for v in variables}
    return summary, sentiment, values


async def extract(
    client: CompletionClient,
    model: str,
    *,
    messages: Sequence[Message],
    tools: Sequence[ToolEvent],
    variables: Sequence[Mapping[str, Any]],
    timeout_s: float = 60.0,
) -> Extraction:
    caller_spoke = any(m.role == "user" and m.text.strip() for m in messages)
    usage = Usage(model=model)
    system = system_prompt(variables)
    data = render_call(messages, tools)
    for _attempt in range(2):
        try:
            completion = await client.complete(
                model,
                [ChatMessage("user", data)],
                system=system,
                max_tokens=2000,
                timeout_s=timeout_s,
                json_mode=True,
                purpose=PURPOSE,
            )
        except (ModelTimeout, ModelError, TimeoutError) as exc:
            raise ExtractionFailed(f"The analysis model did not answer: {exc}") from exc
        usage.add(completion, model)
        parsed = json_object(completion.text)
        if parsed is not None and (parsed.get("summary") or not messages):
            summary, sentiment, values = resolve(parsed, variables, caller_spoke)
            return Extraction(summary or "No conversation was recorded.", sentiment, values, usage)
    raise ExtractionFailed("The analysis model returned no usable answer")


def model_for(config: Mapping[str, Any], fallback: str) -> str:
    """The extraction model: ``advanced.analysis_model``, else the agent's main model (FR-002)."""
    advanced = config.get("advanced")
    for ref in (
        (advanced or {}).get("analysis_model") if isinstance(advanced, Mapping) else None,
        config.get("llm"),
    ):
        if isinstance(ref, Mapping) and ref.get("provider") and ref.get("model"):
            return f"{ref['provider']}/{ref['model']}"
    return fallback
