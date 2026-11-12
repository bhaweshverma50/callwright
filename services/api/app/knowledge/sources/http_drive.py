"""Google Drive over HTTP (022 research R4, R6, R11).

Six endpoints on two fixed Google hosts, through the shared ``httpx.AsyncClient``; no Google client
library. Every response is mapped to the error classes in ``drive.py`` before the sync sees it.
Temporary failures (429, rate-limit 403s, 5xx, network) are retried three times (1, 4 and 16 s,
with jitter) before ``GoogleTemporary`` is raised. The Sheets API is never called (FR-007a).
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.knowledge.sources.drive import (
    DOCX,
    FOLDER,
    MAX_ITEMS,
    AccessToken,
    DriveFolder,
    DriveItem,
    DriveRoot,
    ExportTooLarge,
    FileUnavailable,
    FolderPage,
    GoogleTemporary,
    OAuthExchangeFailed,
    RootKind,
    RootUnavailable,
    SourceTooLarge,
    TokenGrant,
    TokenRevoked,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (an endpoint, not a secret)
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE = "https://www.googleapis.com/drive/v3"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
FILE_FIELDS = "id,name,mimeType,size,md5Checksum,version,webViewLink,trashed"
BACKOFF_S = (1.0, 4.0, 16.0)
TEMPORARY_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "backendError", "internalError"})
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _reason(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        errors = error.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("reason", ""))
        return str(error.get("status", ""))
    return str(error or "")


def _is_temporary(response: httpx.Response) -> bool:
    if response.status_code == 429 or response.status_code >= 500:
        return True
    return response.status_code == 403 and _reason(response) in TEMPORARY_REASONS


def _id_token_claims(id_token: str, client_id: str) -> dict[str, Any]:
    """Claims of the ID token Google's token endpoint returned over TLS (no signature check
    needed for a token received directly from Google, per Google's OpenID documentation)."""
    try:
        payload = id_token.split(".")[1]
        claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as exc:
        raise OAuthExchangeFailed("Google returned an unreadable ID token") from exc
    if claims.get("aud") != client_id or claims.get("iss") not in ISSUERS or not claims.get("sub"):
        raise OAuthExchangeFailed("Google returned an ID token for another client")
    return claims


class HttpDriveClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        client_id: str,
        client_secret: str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._sleep = sleep

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(len(BACKOFF_S) + 1):
            try:
                response = await self._http.request(method, url, timeout=TIMEOUT, **kwargs)
            except httpx.TransportError as exc:
                if attempt == len(BACKOFF_S):
                    raise GoogleTemporary("Google did not answer") from exc
            else:
                if not _is_temporary(response):
                    return response
                if attempt == len(BACKOFF_S):
                    raise GoogleTemporary("Google rate limited or failed the request")
            await self._sleep(BACKOFF_S[attempt] + random.uniform(0, 0.5))  # noqa: S311
        raise GoogleTemporary("Google did not answer")  # pragma: no cover

    async def _drive(self, token: AccessToken, path: str, params: dict[str, Any]) -> httpx.Response:
        response = await self._send(
            "GET", f"{DRIVE}/{path}", params=params, headers={"Authorization": f"Bearer {token.value}"}
        )
        if response.status_code == 401:
            raise TokenRevoked("Google access was revoked or expired")
        return response

    # -- OAuth -------------------------------------------------------------------------------

    async def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> TokenGrant:
        response = await self._send(
            "POST",
            TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if response.status_code != 200:
            raise OAuthExchangeFailed("Google refused the authorization code")
        body = response.json()
        if not body.get("refresh_token"):
            raise OAuthExchangeFailed(
                "Google did not grant offline access. Remove Callwright from your Google account's "
                "third-party access and connect again."
            )
        claims = _id_token_claims(str(body.get("id_token", "")), self._client_id)
        return TokenGrant(
            refresh_token=str(body["refresh_token"]),
            access_token=str(body.get("access_token", "")),
            scopes=tuple(str(body.get("scope", "")).split()),
            subject=str(claims["sub"]),
            email=str(claims.get("email", "")),
        )

    async def refresh(self, refresh_token: str) -> AccessToken:
        response = await self._send(
            "POST",
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code in (400, 401):
            raise TokenRevoked("Google access was revoked or expired")
        if response.status_code != 200:
            raise GoogleTemporary("Google refused to refresh the access token")
        return AccessToken(str(response.json()["access_token"]))

    async def revoke(self, token: str) -> None:
        try:
            await self._http.post(REVOKE_URL, data={"token": token}, timeout=TIMEOUT)
        except httpx.HTTPError:
            return  # best effort: the secret is deleted either way

    # -- Drive -------------------------------------------------------------------------------

    async def get_root(
        self, token: AccessToken, root_kind: RootKind, root_id: str, drive_id: str | None
    ) -> DriveRoot:
        if root_kind == "shared_drive":
            response = await self._drive(token, f"drives/{root_id}", {"fields": "id,name"})
            if response.status_code in (403, 404):
                raise RootUnavailable("The shared drive is not available to this account")
            response.raise_for_status()
            return DriveRoot("shared_drive", root_id, str(response.json()["name"]), root_id)
        response = await self._drive(
            token,
            f"files/{root_id}",
            {"fields": "id,name,mimeType,trashed,driveId", "supportsAllDrives": "true"},
        )
        if response.status_code in (403, 404):
            raise RootUnavailable("The folder was deleted or is no longer shared with this account")
        response.raise_for_status()
        body = response.json()
        if body.get("trashed") or body.get("mimeType") != FOLDER:
            raise RootUnavailable("The folder was deleted or is no longer shared with this account")
        return DriveRoot("folder", root_id, str(body["name"]), body.get("driveId") or drive_id)

    def _list_params(
        self, query: str, drive_id: str | None, page_token: str | None, fields: str
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": query,
            "fields": f"nextPageToken,files({fields})",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if drive_id:
            params.update(corpora="drive", driveId=drive_id)
        if page_token:
            params["pageToken"] = page_token
        return params

    async def list_tree(
        self, token: AccessToken, root: DriveRoot, include_subfolders: bool, max_items: int = MAX_ITEMS
    ) -> list[DriveItem]:
        items: list[DriveItem] = []
        seen = 0
        queue: list[tuple[str, str]] = [(root.id, "")]
        while queue:
            folder, path = queue.pop(0)
            page_token: str | None = None
            while True:
                response = await self._drive(
                    token,
                    "files",
                    self._list_params(
                        f"'{folder}' in parents and trashed = false", root.drive_id, page_token, FILE_FIELDS
                    ),
                )
                if response.status_code in (403, 404):
                    raise RootUnavailable("The folder was deleted or is no longer shared with this account")
                response.raise_for_status()
                body = response.json()
                for f in body.get("files", []):
                    seen += 1
                    if seen > max_items:
                        raise SourceTooLarge(f"The folder holds more than {max_items} items")
                    if f.get("mimeType") == FOLDER:
                        if include_subfolders:
                            queue.append((str(f["id"]), f"{path}/{f['name']}" if path else str(f["name"])))
                        continue
                    items.append(
                        DriveItem(
                            id=str(f["id"]),
                            name=str(f["name"]),
                            mime_type=str(f["mimeType"]),
                            path=path,
                            size=int(f["size"]) if f.get("size") is not None else None,
                            md5=f.get("md5Checksum"),
                            version=str(f["version"]) if f.get("version") is not None else None,
                            web_view_link=f.get("webViewLink"),
                        )
                    )
                page_token = body.get("nextPageToken")
                if not page_token:
                    break
        return items

    async def list_folders(
        self, token: AccessToken, parent: str, drive_id: str | None, page_token: str | None
    ) -> FolderPage:
        start = drive_id if (drive_id and parent == "root") else parent
        params = self._list_params(
            f"'{start}' in parents and mimeType = '{FOLDER}' and trashed = false",
            drive_id,
            page_token,
            "id,name",
        )
        params.update(pageSize=100, orderBy="name")
        response = await self._drive(token, "files", params)
        if response.status_code in (403, 404):
            raise RootUnavailable("The folder is not available to this account")
        response.raise_for_status()
        body = response.json()
        folders = [
            DriveFolder(str(f["id"]), str(f["name"]), "folder", drive_id) for f in body.get("files", [])
        ]
        return FolderPage(folders, body.get("nextPageToken"))

    async def list_shared_drives(self, token: AccessToken, page_token: str | None) -> FolderPage:
        params: dict[str, Any] = {"pageSize": 100, "fields": "nextPageToken,drives(id,name)"}
        if page_token:
            params["pageToken"] = page_token
        response = await self._drive(token, "drives", params)
        response.raise_for_status()
        body = response.json()
        drives = [
            DriveFolder(str(d["id"]), str(d["name"]), "shared_drive", str(d["id"]))
            for d in body.get("drives", [])
        ]
        return FolderPage(drives, body.get("nextPageToken"))

    async def download(self, token: AccessToken, file_id: str) -> bytes:
        response = await self._drive(token, f"files/{file_id}", {"alt": "media", "supportsAllDrives": "true"})
        if response.status_code in (403, 404):
            raise FileUnavailable("The file could not be read")
        response.raise_for_status()
        return response.content

    async def export_docx(self, token: AccessToken, file_id: str) -> bytes:
        response = await self._drive(token, f"files/{file_id}/export", {"mimeType": DOCX})
        if response.status_code == 403 and _reason(response) == "exportSizeLimitExceeded":
            raise ExportTooLarge("The Google Doc is larger than Drive's 10 MB export limit")
        if response.status_code in (403, 404):
            raise FileUnavailable("The file could not be read")
        response.raise_for_status()
        return response.content
