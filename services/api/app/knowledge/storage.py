"""Document storage on 001's object store port (T059, research R17).

Keys are ``ws/{workspace_id}/kb/{kb_id}/{doc_id}/{sha256}.{ext}``. ``put`` writes with
server-side encryption in S3 mode (the core store does that); ``read`` serves the ingestion job;
``signed_url`` is the 10-minute preview link. With ``STORAGE_MODE=fake`` objects live in the API
process memory (no bucket yet), so ingestion then runs inside the API process (``jobs``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.storage import SIGNED_URL_TTL_S, FakeObjectStore, ObjectStore

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def document_key(workspace_id: str, kb_id: str, doc_id: str, sha256: str, file_type: str) -> str:
    return f"ws/{workspace_id}/kb/{kb_id}/{doc_id}/{sha256}.{file_type}"


def is_in_memory(store: ObjectStore) -> bool:
    return isinstance(store, FakeObjectStore)


async def put(store: ObjectStore, key: str, data: bytes, file_type: str) -> None:
    await store.put(key, data, CONTENT_TYPES[file_type])


async def read(store: ObjectStore, key: str) -> bytes | None:
    if isinstance(store, FakeObjectStore):
        found = store.objects.get(key)
        return found[0] if found else None
    client: Any = getattr(store, "_client", None)
    bucket = getattr(store, "bucket", None)
    if client is None or bucket is None:
        return None

    def fetch() -> bytes:
        body: bytes = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return body

    return await asyncio.to_thread(fetch)


async def delete(store: ObjectStore, key: str) -> None:
    await store.delete(key)


async def signed_url(store: ObjectStore, key: str) -> tuple[str, datetime]:
    url = await store.signed_url(key, SIGNED_URL_TTL_S)
    return url, datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_S)
