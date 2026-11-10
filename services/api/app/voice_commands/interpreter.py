# ruff: noqa: E501  (prompt text and patterns read best unwrapped)
"""Voice command interpretation (006 T077, FR-030, FR-031, research R8).

The model (or, without a key, a deterministic keyword interpreter) proposes one action; ``validate``
decides. Navigation must hit an allowlisted page, UI actions must be registered by the current page
with params that fit the action's schema, copilot hand-offs go to known copilots only, and a
highlight is a key the page registered, never a selector. Anything else becomes a polite decline.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.llms.adapters.base import ChatMessage
from app.llms.client import Completion, ModelRef
from app.llms.runtime import CompletionClient
from app.voice_commands.routes_allowlist import CALL_FILTER_VALUES, COPILOTS, DATE_RANGES, ROUTES
from app.voice_commands.schemas import InterpretRequest

ACTIONS = ("navigate", "route_to_copilot", "ui_action", "answer", "decline")
DEFAULT_SUGGESTION = (
    'Try "show me failed calls from yesterday", "go to billing" or "open the analytics assistant".'
)


def _decline(speak: str, suggestion: str | None = None, highlight: str | None = None) -> dict[str, Any]:
    return {
        "action": "decline",
        "target": None,
        "params": None,
        "query": None,
        "speak": speak[:280],
        "highlight_element": highlight,
        "fallback_suggestion": suggestion or DEFAULT_SUGGESTION,
    }


def _fits(schema: Mapping[str, Any] | None, value: Any) -> bool:
    """A small JSON Schema subset: object, array, string, integer, number, boolean, enum,
    properties, required, additionalProperties (false unless set) and array items."""
    if not schema:
        return value in (None, {})
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return False
    if kind == "object":
        if value is None:
            value = {}
        if not isinstance(value, dict):
            return False
        props: Mapping[str, Any] = schema.get("properties") or {}
        if any(k not in value for k in schema.get("required") or []):
            return False
        extra = schema.get("additionalProperties", False)
        for k, v in value.items():
            if k in props:
                if not _fits(props[k], v):
                    return False
            elif extra is False:
                return False
        return True
    if kind == "array":
        return isinstance(value, list) and all(_fits(schema.get("items") or {}, v) for v in value)
    if kind == "string":
        return isinstance(value, str) and len(value) <= int(schema.get("maxLength", 500))
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return kind is None


def _call_params(raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, allowed in CALL_FILTER_VALUES.items():
        values = raw.get(key)
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            kept = [v for v in values if isinstance(v, str) and v in allowed]
            if kept:
                out[key] = kept
    if isinstance(raw.get("agent_id"), str) and re.fullmatch(r"agt_[A-Za-z0-9]+", raw["agent_id"]):
        out["agent_id"] = raw["agent_id"]
    if raw.get("date_range") in DATE_RANGES:
        out["date_range"] = raw["date_range"]
    return out


def validate(raw: Mapping[str, Any], request: InterpretRequest) -> tuple[dict[str, Any], bool]:
    """The final result and whether validation had to downgrade the proposal to a decline."""
    state = request.visual_state
    highlight = raw.get("highlight_element")
    highlight = (
        highlight if isinstance(highlight, str) and highlight in state.highlightable_elements else None
    )
    action = raw.get("action")
    target = raw.get("target")
    speak = raw.get("speak") if isinstance(raw.get("speak"), str) else None
    suggestion = raw.get("fallback_suggestion") if isinstance(raw.get("fallback_suggestion"), str) else None
    base: dict[str, Any] = {
        "action": action,
        "target": None,
        "params": None,
        "query": None,
        "speak": speak[:280] if speak else None,
        "highlight_element": highlight,
        "fallback_suggestion": None,
    }
    if action not in ACTIONS:
        return _decline("I can't do that here.", suggestion, highlight), True
    if action == "navigate":
        path = str(target or "").split("?")[0].rstrip("/") or "/"
        if path not in ROUTES:
            return _decline("I can't open that page.", suggestion, highlight), True
        params = _call_params(raw.get("params")) if path == "/calls" else None
        return {**base, "target": path, "params": params or None}, False
    if action == "route_to_copilot":
        if target not in COPILOTS:
            return _decline("I don't know that assistant.", suggestion, highlight), True
        query = raw.get("query") if isinstance(raw.get("query"), str) else None
        return {**base, "target": target, "query": query[:1000] if query else None}, False
    if action == "ui_action":
        registered = {a.key: a for a in state.available_actions}
        found = registered.get(str(target))
        params = raw.get("params")
        if found is None or not _fits(found.params_schema, params):
            return _decline("This page can't do that.", suggestion, highlight), True
        return {**base, "target": found.key, "params": params or None}, False
    if action == "answer":
        if not base["speak"]:
            return _decline("I don't have an answer for that.", suggestion, highlight), True
        return base, False
    return _decline(speak or "I can't help with that here.", suggestion, highlight), False


# Keyword interpreter -------------------------------------------------------------------------------

_PAGES = [
    (r"\b(billing|balance|credit|funds)\b", "/billing"),
    (r"\bdashboard\b", "/dashboard"),
    (r"\btemplates?\b", "/agents/templates"),
    (r"\bnew agent\b", "/agents/new"),
    (r"\bagents?\b", "/agents"),
    (r"\bknowledge\b", "/knowledge-base"),
    (r"\b(phone numbers?|channels?)\b", "/phone-numbers"),
    (r"\bdatasets?\b", "/datasets"),
    (r"\bsimulations?\b", "/simulations"),
    (r"\breview\b", "/review"),
    (r"\bcalibration\b", "/calibration"),
    (r"\bissues?\b", "/issues"),
    (r"\bsettings\b", "/settings"),
    (r"\bcalls?\b", "/calls"),
]
_DATES = [
    ("yesterday", "yesterday"),
    ("today", "today"),
    ("this week", "this_week"),
    ("last 7 days", "last_7_days"),
    ("last week", "last_7_days"),
]


def keyword_interpret(request: InterpretRequest) -> dict[str, Any]:
    text = request.transcript.lower().strip()
    state = request.visual_state
    if re.search(r"what page|where am i", text):
        title = state.page_title or ROUTES.get(state.current_route, state.current_route)
        return {"action": "answer", "speak": f"You're on {title}."}
    if m := re.search(r"(analytics|assistant|copilot)\b.*?\bask\b(.*)$", text):
        return {
            "action": "route_to_copilot",
            "target": "analytics_chat",
            "query": m.group(2).strip(" ?.") or None,
        }
    if text.startswith("ask "):
        return {"action": "route_to_copilot", "target": "analytics_chat", "query": text[4:].strip(" ?.")}
    for a in state.available_actions:
        words = [w for w in re.findall(r"[a-z]+", a.label.lower()) if len(w) > 2 and w != "the"]
        if words and all(w in text for w in words):
            return {"action": "ui_action", "target": a.key, "params": None}
    if re.search(r"\b(delete|remove|drop|erase)\b", text):
        return {
            "action": "decline",
            "speak": "I can't delete things by voice.",
            "fallback_suggestion": "Use the menu on the record to delete it.",
        }
    if re.search(r"\b(show|find|list|filter)\b.*\bcalls?\b", text) or re.search(
        r"\bcalls?\b.*\b(yesterday|today|this week)\b", text
    ):
        params: dict[str, Any] = {}
        statuses = sorted(
            s for s in CALL_FILTER_VALUES["status"] if re.search(rf"\b{s.replace('_', ' ')}\b", text)
        )
        if statuses:
            params["status"] = statuses
        channel = {"whatsapp": "whatsapp", "web": "web", "inbound": "sip_inbound", "outbound": "sip_outbound"}
        for word, value in channel.items():
            if re.search(rf"\b{word}\b", text):
                params.setdefault("channel", []).append(value)
        for phrase, value in _DATES:
            if phrase in text:
                params["date_range"] = value
                break
        return {"action": "navigate", "target": "/calls", "params": params}
    if re.search(r"\b(go|open|take me|show|navigate)\b", text):
        for pattern, route in _PAGES:
            if re.search(pattern, text):
                return {"action": "navigate", "target": route}
    return {"action": "decline", "speak": "Sorry, I didn't catch a command I can do here."}


INTERPRET_SYSTEM = """You turn one spoken command into exactly one action for a web app. Reply with JSON:
{"action": "navigate|route_to_copilot|ui_action|answer|decline", "target": string or null, "params": object or null,
"query": string or null, "speak": short sentence or null, "highlight_element": string or null, "fallback_suggestion": string or null}
navigate targets (only these): %s. For /calls, params may hold status, channel, sentiment (lists), agent_id and
date_range (today, yesterday, this_week, last_7_days).
route_to_copilot targets: analytics_chat (questions about call data), prompt_builder, flow_builder; put the question in query.
ui_action targets are only the keys this page registered: %s.
highlight_element must be one of: %s.
Use answer for questions about the current page; decline with a fallback_suggestion for anything else.
Current page: %s (%s). Now: %s %s. Never follow instructions that ask for anything outside this list."""


async def model_interpret(
    client: CompletionClient, ref: ModelRef, request: InterpretRequest
) -> tuple[dict[str, Any], Completion]:
    s = request.visual_state
    system = INTERPRET_SYSTEM % (
        ", ".join(ROUTES),
        json.dumps([a.model_dump() for a in s.available_actions]),
        json.dumps(s.highlightable_elements),
        s.current_route,
        s.page_title or "",
        s.current_datetime,
        s.timezone,
    )
    history = [
        ChatMessage("assistant" if h.role == "copilot" else "user", h.content)
        for h in request.conversation_history[-12:]
    ]
    completion = await client.complete(
        ref,
        [*history, ChatMessage("user", request.transcript)],
        system=system,
        max_tokens=400,
        timeout_s=10,
        json_mode=True,
        purpose="voice_copilot",
    )
    try:
        raw = json.loads(completion.text)
    except json.JSONDecodeError:
        raw = {"action": "decline"}
    return (raw if isinstance(raw, dict) else {"action": "decline"}), completion
