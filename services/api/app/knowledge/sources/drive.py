"""Google Drive behind a small port (022 research R11).

``DriveClient`` is everything the platform asks of Google: the OAuth code exchange, token
refresh and revoke for connections, and the Drive reads for sources. ``HttpDriveClient`` talks to
Google; ``FakeDriveClient`` serves an in-memory tree for tests, the mock web mode and local demos.

Errors are classified at this boundary (research R6) so the sync can decide what it may do:

| Error | Meaning | Sync effect |
|---|---|---|
| ``TokenRevoked`` | refresh refused (``invalid_grant``), or a 401 | connection revoked, nothing applied |
| ``RootUnavailable`` | source folder or drive gone or unshared | source access lost, nothing applied |
| ``GoogleTemporary`` | 429, rate limit, 5xx, network | run failed, retried next schedule |
| ``SourceTooLarge`` | listing passed the item cap | run failed, nothing applied |
| ``FileUnavailable`` | one file could not be read | that file failed, the rest continue |
| ``ExportTooLarge`` | a Google Doc over Drive's 10 MB export limit | that file skipped |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
GOOGLE_DOC = "application/vnd.google-apps.document"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_MIME_TYPES = frozenset({GOOGLE_DOC, PDF, DOCX})

SCOPE_DRIVE = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_SHEETS = "https://www.googleapis.com/auth/spreadsheets"
SCOPES = ("openid", "email", SCOPE_DRIVE, SCOPE_SHEETS)

MAX_ITEMS = 5000
EXPORT_LIMIT_BYTES = 10 * 1024 * 1024

RootKind = Literal["folder", "shared_drive"]


class DriveError(Exception):
    """Base of every classified Google error. ``message`` is safe to show and store."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


class TokenRevoked(DriveError):
    pass


class RootUnavailable(DriveError):
    pass


class GoogleTemporary(DriveError):
    pass


class SourceTooLarge(DriveError):
    pass


class FileUnavailable(DriveError):
    pass


class ExportTooLarge(DriveError):
    pass


class OAuthExchangeFailed(DriveError):
    pass


@dataclass(frozen=True)
class TokenGrant:
    """What a successful code exchange returns. Tokens never leave the connectors service."""

    refresh_token: str
    access_token: str
    scopes: tuple[str, ...]
    subject: str
    email: str


@dataclass(frozen=True)
class AccessToken:
    value: str = field(repr=False)


@dataclass(frozen=True)
class DriveRoot:
    kind: RootKind
    id: str
    name: str
    drive_id: str | None = None


@dataclass(frozen=True)
class DriveItem:
    """A file inside a source (folders are walked, never returned)."""

    id: str
    name: str
    mime_type: str
    path: str = ""
    size: int | None = None
    md5: str | None = None
    version: str | None = None
    web_view_link: str | None = None

    @property
    def is_google_doc(self) -> bool:
        return self.mime_type == GOOGLE_DOC

    @property
    def is_shortcut(self) -> bool:
        return self.mime_type == SHORTCUT


@dataclass(frozen=True)
class DriveFolder:
    id: str
    name: str
    kind: RootKind = "folder"
    drive_id: str | None = None


@dataclass(frozen=True)
class FolderPage:
    items: list[DriveFolder]
    next_page_token: str | None = None


class DriveClient(Protocol):
    async def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> TokenGrant: ...

    async def refresh(self, refresh_token: str) -> AccessToken: ...

    async def revoke(self, token: str) -> None: ...

    async def get_root(
        self, token: AccessToken, root_kind: RootKind, root_id: str, drive_id: str | None
    ) -> DriveRoot: ...

    async def list_tree(
        self, token: AccessToken, root: DriveRoot, include_subfolders: bool, max_items: int = MAX_ITEMS
    ) -> list[DriveItem]: ...

    async def list_folders(
        self, token: AccessToken, parent: str, drive_id: str | None, page_token: str | None
    ) -> FolderPage: ...

    async def list_shared_drives(self, token: AccessToken, page_token: str | None) -> FolderPage: ...

    async def download(self, token: AccessToken, file_id: str) -> bytes: ...

    async def export_docx(self, token: AccessToken, file_id: str) -> bytes: ...
