"""``kb_search`` system tool (005 T078, research R15, R16).

Calls ``POST /v1/internal/knowledge/search`` over the call's keep-alive client with a hard 800 ms
timeout. Results reach the LLM as numbered passages with their source and page, under 4,000
characters; nothing found (or a timeout) reads "No relevant information ...". The event records
the kb ids, result count, top score, chunk ids, timeout and embedding cache hit.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from callwright_contract.protocol import KB_DEFAULT_TOP_K, KB_QUERY_MAX_CHARS, KbSearchRequest

from worker.internal_api import InternalApiClient
from worker.tools.base import ToolContext, ToolResult, ToolSpecView

TIMEOUT_S = 0.8
MAX_CHARS = 4000
NOTHING_FOUND = "No relevant information was found in the knowledge base."


def description(knowledge: Sequence[Mapping[str, Any]]) -> str:
    """Function description from the KB names and descriptions captured at publish."""
    parts = []
    for kb in knowledge:
        name = str(kb.get("name") or "").strip()
        about = str(kb.get("description") or "").strip()
        if name:
            parts.append(f"{name} ({about})" if about else name)
    sources = "; ".join(parts) or "the attached documents"
    return (
        f"Search {sources} for facts before answering questions they may cover. Pass a short "
        "search query in the caller's words. Answer only from the passages returned."
    )


def format_passages(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return NOTHING_FOUND
    lines: list[str] = []
    used = 0
    for i, result in enumerate(results, start=1):
        source = str(result.get("file_name") or "document")
        page_from, page_to = result.get("page_from"), result.get("page_to")
        if page_from:
            pages = (
                f"page {page_from}"
                if page_to in (None, page_from)
                else f"pages {page_from}-{page_to}"
            )
            source = f"{source}, {pages}"
        text = f"[{i}] ({source}) {str(result.get('content') or '').strip()}"
        if used + len(text) > MAX_CHARS:
            text = text[: max(0, MAX_CHARS - used)]
        if not text:
            break
        lines.append(text)
        used += len(text) + 1
    return "\n".join(lines)


class KbSearchExecutor:
    def __init__(
        self,
        api: InternalApiClient | None,
        kb_ids: Sequence[str],
        *,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self.api = api
        self.kb_ids = list(kb_ids)
        self.timeout_s = timeout_s

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        query = str(arguments.get("query") or "").strip()[:KB_QUERY_MAX_CHARS]
        kb: dict[str, Any] = {
            "kb_ids": self.kb_ids,
            "result_count": 0,
            "top_score": None,
            "chunk_ids": [],
            "timed_out": False,
            "embedding_cache_hit": False,
        }
        if not query:
            return ToolResult.error("invalid_arguments", "Pass a search query.", kb=kb)
        started = time.perf_counter()
        body = KbSearchRequest(
            call_id=ctx.call_id, query=query, kb_ids=self.kb_ids, top_k=KB_DEFAULT_TOP_K
        )
        data: dict[str, Any] = {}
        try:
            if self.api is not None:
                data = await self.api.kb_search(body, timeout_s=self.timeout_s)
        except TimeoutError:
            kb["timed_out"] = True
        results = list(data.get("results") or [])
        kb.update(
            result_count=len(results),
            top_score=max((float(r.get("score") or 0) for r in results), default=None),
            chunk_ids=[str(r.get("chunk_id")) for r in results],
            embedding_cache_hit=bool(data.get("embedding_cache_hit")),
            search_ms=round((time.perf_counter() - started) * 1000),
        )
        payload = format_passages(results)
        return ToolResult(llm_payload=payload, output=payload, extra={"kb": kb})
