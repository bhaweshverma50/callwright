"""kb_search on calls (005 T072): 800 ms timeout gives empty results, "No relevant information"
text, the 4,000-character cap and the event's kb fields."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from tests.unit.tool_support import make
from worker.tools.kb_search import MAX_CHARS, NOTHING_FOUND, format_passages

KNOWLEDGE = [{"kb_id": "kb_1", "name": "Clinic FAQ", "description": "refunds"}]


def result(i: int, content: str = "Refunds within 14 days.", score: float = 0.8) -> dict[str, Any]:
    return {
        "chunk_id": f"c{i}",
        "kb_id": "kb_1",
        "doc_id": "doc_1",
        "file_name": "refund_policy.pdf",
        "page_from": 1,
        "page_to": 2,
        "heading": "Refunds",
        "content": content,
        "score": score,
    }


def api(results: list[dict[str, Any]], delay: float = 0.0, hit: bool = True) -> Any:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if delay:
            await asyncio.sleep(delay)
        return httpx.Response(
            200,
            json={"results": results, "embedding_ms": 5, "query_ms": 3, "embedding_cache_hit": hit},
        )

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


async def test_passages_and_event_fields() -> None:
    handler = api([result(1), result(2, "Fees apply.", 0.5)])
    h = make([], knowledge=KNOWLEDGE, api_handler=handler)
    payload = await h.tools.dispatch("kb_search", {"query": "refund window"})
    assert payload.startswith("[1] (refund_policy.pdf, pages 1-2) Refunds within 14 days.")
    assert "[2]" in payload
    assert handler.seen[0] == {
        "call_id": "call_test",
        "query": "refund window",
        "kb_ids": ["kb_1"],
        "top_k": 4,
    }
    [event] = h.events()
    assert event["tool_type"] == "kb_search" and event["tool_id"] is None
    kb = event["kb"]
    assert kb["kb_ids"] == ["kb_1"] and kb["result_count"] == 2 and kb["top_score"] == 0.8
    assert (
        kb["chunk_ids"] == ["c1", "c2"]
        and kb["timed_out"] is False
        and kb["embedding_cache_hit"] is True
    )


async def test_nothing_found() -> None:
    h = make([], knowledge=KNOWLEDGE, api_handler=api([]))
    assert await h.tools.dispatch("kb_search", {"query": "parking"}) == NOTHING_FOUND


async def test_timeout_returns_empty() -> None:
    h = make([], knowledge=KNOWLEDGE, api_handler=api([result(1)], delay=0.2))
    h.tools.executors["kb_search"].timeout_s = 0.05  # type: ignore[attr-defined]
    payload = await h.tools.dispatch("kb_search", {"query": "refund"})
    assert payload == NOTHING_FOUND
    assert h.events()[0]["kb"]["timed_out"] is True


def test_character_cap() -> None:
    text = format_passages([result(i, "x" * 1500) for i in range(4)])
    assert len(text) <= MAX_CHARS
