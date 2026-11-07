"""009's model calls on the shared ``llms.runtime``: the model that names issues and drafts fixes,
and the offline replies. Offline (no vendor key) the fake model adapter answers
``purpose="issue_naming"`` and ``purpose="issue_fix_draft"`` deterministically from the structured
context block the prompts carry, so detection and drafting work without keys.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.core.config import Settings
from app.llms.adapters.base import ChatMessage

NAMING = "issue_naming"
DRAFTING = "issue_fix_draft"
FAKE_RULE = (
    "Only state facts, prices and policies you were given. If you do not know, say you will check "
    "and follow up."
)


def model(settings: Settings) -> str:
    """The model that names issues and drafts fixes."""
    return settings.issues_model or settings.simulator_model


def block(text: str, tag: str) -> dict[str, Any]:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _last_user(messages: list[ChatMessage]) -> str:
    return next((m.content for m in reversed(messages) if m.role == "user"), "")


def fake_naming(messages: list[ChatMessage], system: str | None) -> str:
    data = block(_last_user(messages), "cluster")
    reasons = [str(r) for r in data.get("reasons") or [] if str(r).strip()]
    first = reasons[0] if reasons else "the check failed"
    first = first.split(";")[0].strip().rstrip(".")
    title = first[:1].upper() + first[1:]
    node = data.get("node_label")
    if node:
        title = f"{node}: {title}"
    return json.dumps(
        {
            "title": title[:80],
            "description": (
                f"{data.get('call_count') or len(reasons)} calls failed "
                f"{data.get('evaluator') or 'this check'} for a similar reason. Example: {first}."
            )[:1000],
            "suspected_cause": "The agent's instructions do not cover this situation.",
        }
    )


def _fake_payload(kind: str, ctx: Mapping[str, Any]) -> dict[str, Any] | None:
    from app.issues.fixes import guardrail_text

    node = ctx.get("node") or {}
    tools = [t for t in ctx.get("tools") or [] if isinstance(t, Mapping)]
    if kind == "prompt_edit":
        return {"proposed_prompt": guardrail_text(str(ctx.get("prompt") or ""), FAKE_RULE)}
    if kind == "add_guardrail":
        if ctx.get("agent_type") != "flow":
            return {"placement": "agent_prompt", "rule_text": FAKE_RULE}
        if node.get("node_id"):
            return {"placement": "node", "node_id": node["node_id"], "rule_text": FAKE_RULE}
        return {"placement": "all_agent_nodes", "rule_text": FAKE_RULE}
    if kind == "node_prompt_edit" and node.get("node_id"):
        return {
            "node_id": node["node_id"],
            "proposed_instructions": guardrail_text(str(node.get("instructions") or ""), FAKE_RULE),
        }
    if kind == "tool_description_edit" and tools:
        tool = tools[0]
        return {
            "tool_id": tool["tool_id"],
            "proposed_description": f"{str(tool.get('description') or '').rstrip()} "
            "Use it only when the caller asks for this, and never guess its result.".strip(),
        }
    if kind == "transition_condition_edit":
        edge = next((e for e in node.get("outgoing") or [] if e.get("trigger") == "llm_condition"), None)
        if edge:
            return {
                "edge_id": edge["edge_id"],
                "proposed_condition": f"{str(edge.get('condition') or '').rstrip()} "
                "Move on only after the caller confirmed.".strip(),
            }
    if kind == "add_transition" and node.get("node_id"):
        target = next(
            (
                n
                for n in ctx.get("nodes") or []
                if n.get("node_id") != node["node_id"] and n.get("type") not in ("start",)
            ),
            None,
        )
        taken = {e.get("label") for e in node.get("outgoing") or []}
        label, n = "fix_route", 2
        while label in taken:
            label, n = f"fix_route_{n}", n + 1
        if target:
            return {
                "target_node_id": target["node_id"],
                "edge_label": label,
                "handoff_condition": "The caller's request is handled and they need the next step.",
            }
    if kind == "node_tool_attachment" and node.get("node_id"):
        on_node = set(node.get("tool_ids") or [])
        spare = next((t["tool_id"] for t in tools if t["tool_id"] not in on_node), None)
        if spare:
            return {"tools_to_attach": [spare], "tools_to_detach": []}
        if on_node:
            return {"tools_to_attach": [], "tools_to_detach": [sorted(on_node)[0]]}
    if kind == "kb_attach":
        spare_kb = next((k["kb_id"] for k in ctx.get("knowledge_bases") or [] if not k.get("attached")), None)
        if spare_kb:
            return {"kb_ids_to_attach": [spare_kb], "uncovered_topics": []}
        return {
            "kb_ids_to_attach": [],
            "uncovered_topics": [str((ctx.get("issue") or {}).get("title") or "")],
        }
    return None


def fake_draft(messages: list[ChatMessage], system: str | None) -> str:
    user = _last_user(messages)
    if "[malformed]" in user.lower():
        return "{not json"
    ctx = block(user, "fix_context")
    allowed = [str(k) for k in ctx.get("allowed_kinds") or []]
    kind = str(ctx.get("requested_kind") or ctx.get("recommended_kind") or (allowed[0] if allowed else ""))
    payload = _fake_payload(kind, ctx)
    if payload is None and "add_guardrail" in allowed:
        kind, payload = "add_guardrail", _fake_payload("add_guardrail", ctx)
    title = str((ctx.get("issue") or {}).get("title") or "this issue")
    return json.dumps(
        {
            "kind": kind,
            "rationale": f"The failing calls show the agent lacks a clear rule for: {title}. "
            "This change states the rule where the agent reads it.",
            "payload": payload or {},
        }
    )


def register_fakes() -> None:
    from app.llms.adapters.fake import PURPOSE_REPLIES

    PURPOSE_REPLIES.setdefault(NAMING, fake_naming)
    PURPOSE_REPLIES.setdefault(DRAFTING, fake_draft)
