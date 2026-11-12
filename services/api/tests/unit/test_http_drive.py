"""The HTTP Drive client (022 T012): fixed Google hosts only, never the Sheets API (FR-007a), and
Google's responses mapped to the research R6 error classes."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import httpx
import pytest

from app.knowledge.sources.drive import (
    AccessToken,
    DriveRoot,
    ExportTooLarge,
    FileUnavailable,
    GoogleTemporary,
    OAuthExchangeFailed,
    RootUnavailable,
    TokenRevoked,
)
from app.knowledge.sources.http_drive import HttpDriveClient

TOKEN = AccessToken("tok")
ALLOWED_HOSTS = {"oauth2.googleapis.com", "www.googleapis.com"}


def _id_token(aud: str = "client-1", iss: str = "https://accounts.google.com") -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"aud": aud, "iss": iss, "sub": "sub-1", "email": "a@b.c"}).encode()
    )
    return f"h.{payload.decode().rstrip('=')}.s"


def _client(handler: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]) -> HttpDriveClient:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def no_sleep(_: float) -> None:
        return None

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return HttpDriveClient(http, "client-1", "secret-1", sleep=no_sleep)


def _error(status: int, reason: str = "") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "errors": [{"reason": reason}]}})


async def test_full_flow_touches_only_drive_and_oauth_hosts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            if body["grant_type"] == "authorization_code":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "a",
                        "refresh_token": "r",
                        "scope": "openid email https://www.googleapis.com/auth/drive.readonly",
                        "id_token": _id_token(),
                    },
                )
            return httpx.Response(200, json={"access_token": "a2"})
        if path.endswith("/files/root1"):
            return httpx.Response(
                200,
                json={"id": "root1", "name": "Policies", "mimeType": "application/vnd.google-apps.folder"},
            )
        if path.endswith("/files") and "pageToken" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "nextPageToken": "p2",
                    "files": [
                        {
                            "id": "f1",
                            "name": "A.pdf",
                            "mimeType": "application/pdf",
                            "size": "10",
                            "md5Checksum": "m",
                        }
                    ],
                },
            )
        if path.endswith("/files"):
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "id": "g1",
                            "name": "Doc",
                            "mimeType": "application/vnd.google-apps.document",
                            "version": "7",
                        }
                    ]
                },
            )
        if path.endswith("/export"):
            return httpx.Response(200, content=b"PK docx")
        return httpx.Response(200, content=b"%PDF-1.4")

    client = _client(handler, seen)
    grant = await client.exchange_code(
        "code", "verifier", "http://localhost:5180/settings/connections/callback"
    )
    assert grant.subject == "sub-1" and grant.refresh_token == "r"
    token = await client.refresh("r")
    root = await client.get_root(token, "folder", "root1", None)
    items = await client.list_tree(token, root, include_subfolders=True)
    assert [i.id for i in items] == ["f1", "g1"] and items[1].version == "7"
    await client.download(token, "f1")
    await client.export_docx(token, "g1")
    hosts = {r.url.host for r in seen}
    assert hosts <= ALLOWED_HOSTS
    assert not any("sheets" in str(r.url) for r in seen)


async def test_id_token_for_another_client_is_refused() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        lambda r: httpx.Response(
            200, json={"access_token": "a", "refresh_token": "r", "id_token": _id_token(aud="other")}
        ),
        seen,
    )
    with pytest.raises(OAuthExchangeFailed):
        await client.exchange_code("code", "v", "uri")


async def test_missing_refresh_token_is_refused() -> None:
    client = _client(lambda r: httpx.Response(200, json={"access_token": "a", "id_token": _id_token()}), [])
    with pytest.raises(OAuthExchangeFailed):
        await client.exchange_code("code", "v", "uri")


@pytest.mark.parametrize(
    ("response", "call", "error"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "refresh", TokenRevoked),
        (_error(401), "root", TokenRevoked),
        (_error(404, "notFound"), "root", RootUnavailable),
        (_error(403, "insufficientFilePermissions"), "root", RootUnavailable),
        (_error(429), "root", GoogleTemporary),
        (_error(403, "rateLimitExceeded"), "root", GoogleTemporary),
        (_error(403, "userRateLimitExceeded"), "root", GoogleTemporary),
        (_error(500), "root", GoogleTemporary),
        (_error(503), "root", GoogleTemporary),
        (_error(403, "forbidden"), "download", FileUnavailable),
        (_error(403, "exportSizeLimitExceeded"), "export", ExportTooLarge),
    ],
)
async def test_errors_are_classified(response: httpx.Response, call: str, error: type[Exception]) -> None:
    seen: list[httpx.Request] = []
    client = _client(lambda r: response, seen)
    with pytest.raises(error):
        if call == "refresh":
            await client.refresh("r")
        elif call == "root":
            await client.get_root(TOKEN, "folder", "x", None)
        elif call == "download":
            await client.download(TOKEN, "x")
        else:
            await client.export_docx(TOKEN, "x")
    if error is GoogleTemporary:
        assert len(seen) == 4  # first try plus three retries


async def test_network_errors_become_temporary_after_retries() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    seen: list[httpx.Request] = []
    client = _client(boom, seen)
    with pytest.raises(GoogleTemporary):
        await client.list_tree(TOKEN, DriveRoot("folder", "x", "X"), True)
    assert len(seen) == 4
