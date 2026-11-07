"""S3-compatible object storage (ambient audio uploads, KB documents) and signed GET links.

``STORAGE_MODE=s3`` uses boto3 against ``S3_ENDPOINT_URL`` (AWS S3, or the compose MinIO on
port 59000) and serves 10-minute presigned URLs. ``ObjectSigner`` signs GETs for any bucket
(uploaded ambience, call recordings); the recordings bucket uses the ``RECORDINGS_S3_*``
endpoint and keys when set, the general ones otherwise. ``STORAGE_MODE=fake`` (default, tests and
offline dev) keeps objects in process memory and signs URLs for the dev-only route
``GET /v1/dev/storage/{key}``, which is never part of the contract or mounted in production.
Objects are written with server-side encryption in S3 mode (Principle V).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request, Response
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import not_found

SIGNED_URL_TTL_S = 600


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def signed_url(self, key: str, expires_s: int = SIGNED_URL_TTL_S) -> str: ...


class ObjectSigner(Protocol):
    def presign_get(self, bucket: str, key: str, ttl_s: int, download_name: str | None = None) -> str: ...


class DevSigner:
    """HMAC-signed links to the dev-only preview route; the bucket is not part of the link."""

    def __init__(self, base_url: str, secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._secret = secret.encode()

    def signature(self, key: str, expires: int) -> str:
        return hmac.new(self._secret, f"{key}:{expires}".encode(), hashlib.sha256).hexdigest()

    def presign_get(self, bucket: str, key: str, ttl_s: int, download_name: str | None = None) -> str:
        expires = int(time.time()) + ttl_s
        query = urlencode({"expires": expires, "sig": self.signature(key, expires)})
        return f"{self.base_url}/v1/dev/storage/{quote(key)}?{query}"


class FakeObjectStore:
    """In-memory store with HMAC-signed preview URLs (development and tests)."""

    def __init__(self, base_url: str, secret: str) -> None:
        self._signer = DevSigner(base_url, secret)
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def signed_url(self, key: str, expires_s: int = SIGNED_URL_TTL_S) -> str:
        return self._signer.presign_get("", key, expires_s)

    def read(self, key: str, expires: int, signature: str) -> tuple[bytes, str] | None:
        if expires < int(time.time()):
            return None
        if not hmac.compare_digest(self._signer.signature(key, expires), signature):
            return None
        return self.objects.get(key)


@dataclass(frozen=True)
class S3Access:
    endpoint: str | None
    region: str
    access_key: SecretStr | None
    secret_key: SecretStr | None


def recordings_s3(settings: Settings) -> S3Access:
    """The recordings bucket's S3 endpoint and keys (egress uploads, signed links): the
    ``RECORDINGS_S3_*`` values, else the general object store's."""
    return S3Access(
        settings.recordings_s3_endpoint or settings.s3_endpoint_url,
        settings.recordings_s3_region,
        settings.recordings_s3_access_key or settings.s3_access_key_id,
        settings.recordings_s3_secret_key or settings.s3_secret_access_key,
    )


def _s3_client(
    endpoint: str | None, region: str, access_key: SecretStr | None, secret_key: SecretStr | None
) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key.get_secret_value() if access_key else None,
        aws_secret_access_key=secret_key.get_secret_value() if secret_key else None,
    )


class S3Signer:
    """Presigned GETs. Presigning is computed locally, no request leaves the process."""

    def __init__(self, settings: Settings) -> None:
        self._recordings_bucket = settings.recordings_bucket
        self._default = _s3_client(
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.s3_access_key_id,
            settings.s3_secret_access_key,
        )
        access = recordings_s3(settings)
        self._recordings = _s3_client(access.endpoint, access.region, access.access_key, access.secret_key)

    def presign_get(self, bucket: str, key: str, ttl_s: int, download_name: str | None = None) -> str:
        client = self._recordings if bucket == self._recordings_bucket else self._default
        params = {"Bucket": bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        url: str = client.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_s)
        return url


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self._client = _s3_client(
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.s3_access_key_id,
            settings.s3_secret_access_key,
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


def build_signer(settings: Settings) -> ObjectSigner:
    if settings.storage_mode == "s3":
        return S3Signer(settings)
    return DevSigner(settings.api_base_url, settings.service_token.get_secret_value())


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
