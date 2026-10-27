"""``phrase_check`` custom evaluator: a required or forbidden phrase or pattern (FR-009, FR-012).

Patterns are compiled with RE2 (linear time, no backreferences or lookarounds), so a user
pattern can never run unbounded. Plain-text mode escapes the phrase. Matching runs on the chosen
speaker's lines; the rationale quotes the first match with its line number.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import re2

from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, Evaluator, ItemResult, quote

MAX_PATTERN = 500
MAX_TEXT = 10_000
TARGET_ROLES = {"agent": ("agent",), "user": ("user",), "both": ("agent", "user")}
SPEAKER = {"agent": "agent", "user": "caller", "both": "agent or caller"}


class PatternError(ValueError):
    pass


def compile_pattern(pattern: str, *, is_regex: bool, case_sensitive: bool) -> Any:
    if not pattern or len(pattern) > MAX_PATTERN:
        raise PatternError(f"Enter a pattern of 1 to {MAX_PATTERN} characters")
    source = pattern if is_regex else re.escape(pattern)
    options = re2.Options()
    options.case_sensitive = case_sensitive
    options.max_mem = 8 << 20
    options.log_errors = False
    try:
        return re2.compile(source, options)
    except re2.error as exc:
        detail = exc.args[0].decode() if exc.args and isinstance(exc.args[0], bytes) else str(exc)
        raise PatternError(f"This pattern is not valid: {detail}") from exc


class PhraseCheck(Evaluator):
    name = "phrase_check"
    display_name = "Required or forbidden phrase"
    description = "Checks that a phrase or pattern is said, or never said, by the agent, the caller or both."

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        return check_phrase(ctx, self.config)


def check_phrase(ctx: EvalContext, config: Mapping[str, Any]) -> EvalOutcome:
    pattern = str(config["pattern"])
    regex = compile_pattern(
        pattern, is_regex=bool(config.get("is_regex")), case_sensitive=bool(config.get("case_sensitive"))
    )
    target = str(config.get("target") or "agent")
    roles = TARGET_ROLES.get(target, ("agent",))
    lines = [m for m in ctx.messages if m.role in roles]
    if not lines:
        return EvalOutcome.not_applicable(f"the {SPEAKER.get(target, 'agent')} never spoke")
    hit = None
    for m in lines:
        match = regex.search(m.text[:MAX_TEXT])
        if match:
            hit = (m, match.group(0))
            break
    mode = str(config.get("mode") or "forbidden")
    who = SPEAKER.get(target, "agent")
    if hit:
        message, matched = hit
        evidence = {"turn_indices": [message.index], "quote": quote(message.text)}
        if mode == "forbidden":
            rationale = f'Forbidden phrase "{matched}" said by the {who} on line {message.index}: "{quote(message.text)}"'
            item = ItemResult("fail", 0.0, rationale, evidence=evidence)
        else:
            rationale = f'Required phrase found on line {message.index}: "{quote(message.text)}"'
            item = ItemResult("pass", 1.0, rationale, evidence=evidence)
    elif mode == "forbidden":
        item = ItemResult("pass", 1.0, f'The {who} never said "{pattern}".')
    else:
        item = ItemResult("fail", 0.0, f'The {who} never said the required "{pattern}".')
    return EvalOutcome([item], rationale=item.rationale)
