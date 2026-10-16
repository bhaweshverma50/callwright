"""S3-compatible object storage (ambient audio uploads first; recordings and KB documents later).

``STORAGE_MODE=s3`` uses boto3 against ``S3_ENDPOINT_URL`` (AWS S3, or the compose MinIO on
port 59000) and serves 10-minute presigned URLs. ``STORAGE_MODE=fake`` (default, tests and
offline dev) keeps objects in process memory and signs URLs for the dev-only route
``GET /v1/dev/storage/{key}``, which is never part of the contract or mounted in production.
Objects are written with server-side encryption in S3 mode (Principle V).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request, Response

from app.core.config import Settings
from app.core.errors import not_found

SIGNED_URL_TTL_S = 600


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def signed_url(self, key: str, expires_s: int = SIGNED_URL_TTL_S) -> str: ...


class FakeObjectStore:
    """In-memory store with HMAC-signed preview URLs (development and tests)."""

    def __init__(self, base_url: str, secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._secret = secret.encode()
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def _signature(self, key: str, expires: int) -> str:
        return hmac.new(self._secret, f"{key}:{expires}".encode(), hashlib.sha256).hexdigest()

    async def signed_url(self, key: str, expires_s: int = SIGNED_URL_TTL_S) -> str:
        expires = int(time.time()) + expires_s
        query = urlencode({"expires": expires, "sig": self._signature(key, expires)})
        return f"{self.base_url}/v1/dev/storage/{quote(key)}?{query}"

    def read(self, key: str, expires: int, signature: str) -> tuple[bytes, str] | None:
        if expires < int(time.time()):
            return None
        if not hmac.compare_digest(self._signature(key, expires), signature):
            return None
        return self.objects.get(key)


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=(
                settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
            ),
            aws_secret_access_key=(
                settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
            ),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def signed_url(self, key: str, expires_s: int = SIGNED_URL_TTL_S) -> str:
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_s,
        )
        return url


def build_store(settings: Settings) -> ObjectStore:
    if settings.storage_mode == "s3":
        return S3ObjectStore(settings)
    return FakeObjectStore(settings.api_base_url, settings.service_token.get_secret_value())


dev_router = APIRouter(prefix="/dev", tags=["dev"], include_in_schema=False)


@dev_router.get("/storage/{key:path}")
async def dev_storage(key: str, expires: int, sig: str, request: Request) -> Response:
    store = request.app.state.storage
    if not isinstance(store, FakeObjectStore):
        raise not_found("object")
    found = store.read(key, expires, sig)
    if found is None:
        raise not_found("object")
    data, content_type = found
    return Response(content=data, media_type=content_type)
