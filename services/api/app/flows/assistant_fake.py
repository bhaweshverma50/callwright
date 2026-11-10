"""Deterministic flow assistant for development and tests (no model keys).

Reads the graph from the ``<graph>`` block of the system prompt and answers a few request
shapes: inserting a date-of-birth (or other details) Task step after the first conversational
node, sending a topic to a person through a Transfer node, renaming the flow, and otherwise a
clarifying question with no operations.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.flows.assistant import PURPOSE
from app.flows.schemas import CONVERSATIONAL
from app.llms.adapters.base import ChatMessage
from app.llms.adapters.fake import PURPOSE_REPLIES

_GRAPH = re.compile(r"<graph>\n?(.*?)\n?</graph>", re.DOTALL)


def _graph(system: str | None) -> dict[str, Any]:
    match = _GRAPH.search(system or "")
    if not match:
        return {"nodes": [], "edges": []}
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return {"nodes": [], "edges": []}
    return data if isinstance(data, dict) else {"nodes": [], "edges": []}


def reply(messages: list[ChatMessage], system: str | None) -> str:
    last = next((m.content for m in reversed(messages) if m.role == "user"), "")
    lowered = last.lower()
    if "[malformed]" in lowered:
        return "{not json"
    graph = _graph(system)
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    first = next((n for n in nodes if n.get("type") in CONVERSATIONAL), None)
    ops: list[dict[str, Any]] = []
    parts: list[str] = []
    rename = re.search(r"rename (?:the flow |it )?to ['\"]?([^'\"]+?)['\"]?\s*$", last, re.IGNORECASE)
    if rename:
        ops.append({"op": "rename_flow", "name": rename.group(1).strip()})
        parts.append(f"I renamed the flow to {rename.group(1).strip()}.")
    if first is not None and ("birth" in lowered or "collect" in lowered):
        out = next(
            (e for e in edges if e.get("source") == first["id"] and e.get("trigger") == "llm_condition"), None
        )
        field = "date_of_birth" if "birth" in lowered else "details"
        ops.append(
            {
                "op": "add_node",
                "node": {
                    "id": "tmp_task",
                    "type": "task",
                    "label": "Date of birth" if "birth" in lowered else "Collect details",
                    "config": {
                        "instructions": "Ask for the caller's date of birth and confirm it back to them."
                        if "birth" in lowered
                        else "Collect the details the caller needs to give.",
                        "begin_message": "Before we continue, could I take your date of birth?"
                        if "birth" in lowered
                        else "Could I take a few details first?",
                        "fields": [
                            {
                                "name": field,
                                "type": "string",
                                "description": "Date of birth as day, month and year"
                                if "birth" in lowered
                                else "The details",
                                "required": True,
                            }
                        ],
                        "max_rounds": 5,
                    },
                },
            }
        )
        if out is not None:
            ops += [
                {"op": "remove_edge", "edge_id": out["id"]},
                {
                    "op": "add_edge",
                    "edge": {
                        "source": first["id"],
                        "target": "tmp_task",
                        "trigger": "llm_condition",
                        "label": out.get("label") or "Ready to book",
                        "condition": out.get("condition") or "The caller is ready to continue",
                    },
                },
                {
                    "op": "add_edge",
                    "edge": {"source": "tmp_task", "target": out["target"], "trigger": "success"},
                },
            ]
        parts.append(
            "I added a step that collects the caller's date of birth."
            if "birth" in lowered
            else "I added a step that collects details."
        )
    if first is not None and any(w in lowered for w in ("human", "person", "transfer")):
        topic = "billing" if "billing" in lowered else "a person"
        ops += [
            {
                "op": "add_node",
                "node": {
                    "id": "tmp_transfer",
                    "type": "transfer",
                    "label": "Billing team" if topic == "billing" else "Transfer",
                    "config": {
                        "transfer": {
                            "routing_type": "static",
                            "number": "+14155550100",
                            "transfer_type": "cold",
                        }
                    },
                },
            },
            {
                "op": "add_edge",
                "edge": {
                    "source": first["id"],
                    "target": "tmp_transfer",
                    "trigger": "llm_condition",
                    "label": "Billing question" if topic == "billing" else "Wants a person",
                    "condition": "The caller asks about a bill, a charge or a payment"
                    if topic == "billing"
                    else "The caller asks to speak with a person",
                },
            },
        ]
        parts.append("Billing questions now go to a person. Check the transfer number before publishing.")
    if not ops:
        return json.dumps(
            {
                "message": "Tell me which step to add or change, for example: add a step that "
                "collects the caller's date of birth.",
                "flow_name": None,
                "operations": [],
            }
        )
    return json.dumps({"message": " ".join(parts), "flow_name": None, "operations": ops})


def register_fakes() -> None:
    PURPOSE_REPLIES.setdefault(PURPOSE, reply)
