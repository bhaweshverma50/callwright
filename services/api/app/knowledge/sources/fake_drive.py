"""In-memory Google Drive for tests, the mock web mode and local demos (022 research R11).

One instance per process (``shared_fake()``) so the dev routes, the API and an inline sync all see
the same tree. Switches simulate the failures in research R6: ``revoked`` (token refresh refused),
``outage`` (every call rate limited), ``unshared`` (a root folder or drive no longer readable),
``corrupt`` (a file downloads as garbage), ``unavailable`` (one file 403s) and ``fail_after_items``
(the listing breaks part way, like a failure on page 3 of 5). ``calls`` counts every request, so a
test can prove that calls never reach Drive (SC-004).
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field

from app.knowledge.sources.drive import (
    DOCX,
    EXPORT_LIMIT_BYTES,
    FOLDER,
    GOOGLE_DOC,
    MAX_ITEMS,
    PDF,
    SCOPES,
    SHORTCUT,
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
from app.knowledge.sources.fake_content import make_docx, make_pdf

SHEET = "application/vnd.google-apps.spreadsheet"
MY_DRIVE = "root"
FAKE_SUBJECT = "fake-google-subject-1"
FAKE_EMAIL = "drive.owner@example.com"
MB = 1024 * 1024


@dataclass
class FakeNode:
    id: str
    name: str
    mime_type: str
    parent: str
    paragraphs: list[str] = field(default_factory=list)
    content: bytes | None = None
    version: int = 1
    size_override: int | None = None
    trashed: bool = False


class FakeDriveClient:
    def __init__(self) -> None:
        self.reset()

    # -- state -------------------------------------------------------------------------------

    def reset(self) -> None:
        self.nodes: dict[str, FakeNode] = {}
        self.shared_drives: dict[str, str] = {}
        self.granted_scopes: tuple[str, ...] = SCOPES
        self.consent_decline = False
        self.account_subject = FAKE_SUBJECT
        self.account_email = FAKE_EMAIL
        self.revoked = False
        self.outage = False
        self.unshared: set[str] = set()
        self.corrupt: set[str] = set()
        self.unavailable: set[str] = set()
        self.fail_after_items: int | None = None
        self.item_cap: int | None = None
        self.revoked_tokens: list[str] = []
        self.calls = 0
        self._ids = itertools.count(1)

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):04d}"

    def add_folder(self, name: str, parent: str = MY_DRIVE, folder_id: str | None = None) -> str:
        node_id = folder_id or self._new_id("fld")
        self.nodes[node_id] = FakeNode(node_id, name, FOLDER, parent)
        return node_id

    def add_shared_drive(self, name: str, drive_id: str | None = None) -> str:
        drive = drive_id or self._new_id("drv")
        self.shared_drives[drive] = name
        return drive

    def add_doc(self, parent: str, name: str, paragraphs: list[str]) -> str:
        node_id = self._new_id("doc")
        self.nodes[node_id] = FakeNode(node_id, name, GOOGLE_DOC, parent, paragraphs=list(paragraphs))
        return node_id

    def add_pdf(self, parent: str, name: str, lines: list[str], size_override: int | None = None) -> str:
        node_id = self._new_id("pdf")
        self.nodes[node_id] = FakeNode(
            node_id,
            name,
            PDF,
            parent,
            paragraphs=list(lines),
            content=make_pdf([lines]),
            size_override=size_override,
        )
        return node_id

    def add_docx(self, parent: str, name: str, paragraphs: list[str]) -> str:
        node_id = self._new_id("dcx")
        content = make_docx(name, paragraphs)
        self.nodes[node_id] = FakeNode(
            node_id, name, DOCX, parent, paragraphs=list(paragraphs), content=content
        )
        return node_id

    def add_other(self, parent: str, name: str, mime_type: str = SHEET) -> str:
        node_id = self._new_id("oth")
        self.nodes[node_id] = FakeNode(node_id, name, mime_type, parent, content=b"other")
        return node_id

    def edit(self, node_id: str, paragraphs: list[str]) -> None:
        node = self.nodes[node_id]
        node.paragraphs = list(paragraphs)
        if node.mime_type == PDF:
            node.content = make_pdf([paragraphs])
        elif node.mime_type == DOCX:
            node.content = make_docx(node.name, paragraphs)
        node.version += 1

    def touch(self, node_id: str) -> None:
        """A metadata-only change (sharing, comments): the version moves, the text does not."""
        self.nodes[node_id].version += 1

    def rename(self, node_id: str, name: str) -> None:
        self.nodes[node_id].name = name

    def move(self, node_id: str, parent: str) -> None:
        self.nodes[node_id].parent = parent

    def delete(self, node_id: str) -> None:
        self.nodes[node_id].trashed = True

    def seed(self, preset: str) -> dict[str, str]:
        """Presets used by the quickstart and the tests. Returns the root folder ids by name."""
        if preset == "clinic":
            root = self.add_folder("Clinic policies")
            sub = self.add_folder("2026", parent=root)
            docs = {
                "Clinic hours": [
                    "The clinic is open Monday to Saturday from 9 am to 7 pm.",
                    "Sunday is closed.",
                ],
                "Cancellation policy": [
                    "Appointments cancelled with less than 24 hours notice are charged a 40 dollar fee."
                ],
                "Our doctors": ["Dr Mehta handles general medicine.", "Dr Rao is our paediatrician."],
                "Insurance": ["We accept Star Health, HDFC Ergo and ICICI Lombard insurance cards."],
                "Lab tests": ["Blood test reports are ready within 24 hours of sample collection."],
            }
            for name, paragraphs in docs.items():
                self.add_doc(root, name, paragraphs)
            self.add_doc(
                sub, "Vaccination drive", ["The 2026 flu vaccination drive runs every Saturday in October."]
            )
            self.add_pdf(
                root, "Refund policy.pdf", ["Prepaid treatment plans can be refunded within 14 days."]
            )
            self.add_pdf(root, "Parking.pdf", ["Free parking is available in the basement for two hours."])
            self.add_docx(root, "Visitor rules.docx", ["Two visitors are allowed per patient at a time."])
            self.add_docx(root, "Pharmacy.docx", ["The in-house pharmacy is open until 9 pm every day."])
            self.add_other(root, "Slots", SHEET)
            self.add_pdf(root, "Scanned archive.pdf", ["Old scans"], size_override=30 * MB)
            return {"Clinic policies": root}
        if preset == "property":
            root = self.add_folder("Listings")
            for n in range(1, 6):
                self.add_doc(
                    root,
                    f"Listing {n}",
                    [f"Listing {n}: a {n + 1} bedroom flat in Pune, rent {20 + n} thousand."],
                )
            return {"Listings": root}
        if preset == "big":
            root = self.add_folder("Big folder")
            for n in range(1, 101):
                self.add_doc(root, f"Note {n:03d}", [f"Internal note number {n} about procedure {n * 7}."])
            return {"Big folder": root}
        raise ValueError(f"unknown preset {preset}")

    # -- DriveClient -------------------------------------------------------------------------

    def _call(self) -> None:
        self.calls += 1
        if self.outage:
            raise GoogleTemporary("Google rate limited the request")

    async def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> TokenGrant:
        self._call()
        if not code or code == "bad":
            raise OAuthExchangeFailed("Google refused the authorization code")
        subject, email = self.account_subject, self.account_email
        if code.startswith("account:"):  # "account:<subject>:<email>" signs in as someone else
            _, subject, email = code.split(":", 2)
        self.revoked = False
        return TokenGrant(
            refresh_token=f"fake-refresh-{subject}",
            access_token="fake-access",  # noqa: S106 (fake token)
            scopes=self.granted_scopes,
            subject=subject,
            email=email,
        )

    async def refresh(self, refresh_token: str) -> AccessToken:
        self._call()
        if self.revoked:
            raise TokenRevoked("Google access was revoked or expired")
        return AccessToken("fake-access")

    async def revoke(self, token: str) -> None:
        self.calls += 1
        self.revoked_tokens.append(token)

    async def get_root(
        self, token: AccessToken, root_kind: RootKind, root_id: str, drive_id: str | None
    ) -> DriveRoot:
        self._call()
        if root_id in self.unshared:
            raise RootUnavailable("The folder was deleted or is no longer shared with this account")
        if root_kind == "shared_drive":
            if root_id not in self.shared_drives:
                raise RootUnavailable("The shared drive is not available to this account")
            return DriveRoot("shared_drive", root_id, self.shared_drives[root_id], root_id)
        node = self.nodes.get(root_id)
        if node is None or node.trashed or node.mime_type != FOLDER:
            raise RootUnavailable("The folder was deleted or is no longer shared with this account")
        return DriveRoot("folder", root_id, node.name, drive_id)

    def _children(self, parent: str) -> list[FakeNode]:
        return sorted(
            (n for n in self.nodes.values() if n.parent == parent and not n.trashed),
            key=lambda n: (n.name, n.id),
        )

    def _item(self, node: FakeNode, path: str) -> DriveItem:
        binary = node.mime_type not in (GOOGLE_DOC, SHEET, SHORTCUT)
        size = node.size_override or (len(node.content) if binary and node.content is not None else None)
        md5 = hashlib.md5(node.content).hexdigest() if binary and node.content is not None else None  # noqa: S324
        link = (
            f"https://docs.google.com/document/d/{node.id}/edit"
            if node.mime_type == GOOGLE_DOC
            else f"https://drive.google.com/file/d/{node.id}/view"
        )
        return DriveItem(
            id=node.id,
            name=node.name,
            mime_type=node.mime_type,
            path=path,
            size=size,
            md5=md5,
            version=str(node.version),
            web_view_link=link,
        )

    async def list_tree(
        self, token: AccessToken, root: DriveRoot, include_subfolders: bool, max_items: int = MAX_ITEMS
    ) -> list[DriveItem]:
        self._call()
        if root.id in self.unshared:
            raise RootUnavailable("The folder was deleted or is no longer shared with this account")
        max_items = min(max_items, self.item_cap or max_items)
        items: list[DriveItem] = []
        seen = 0
        queue: list[tuple[str, str]] = [(root.id, "")]
        while queue:
            folder, path = queue.pop(0)
            for node in self._children(folder):
                seen += 1
                if seen > max_items:
                    raise SourceTooLarge(f"The folder holds more than {max_items} items")
                if self.fail_after_items is not None and seen > self.fail_after_items:
                    raise GoogleTemporary("Google stopped answering part way through the listing")
                if node.mime_type == FOLDER:
                    if include_subfolders:
                        queue.append((node.id, f"{path}/{node.name}" if path else node.name))
                    continue
                items.append(self._item(node, path))
        return items

    async def list_folders(
        self, token: AccessToken, parent: str, drive_id: str | None, page_token: str | None
    ) -> FolderPage:
        self._call()
        start = drive_id if (drive_id and parent == MY_DRIVE) else parent
        folders = [
            DriveFolder(n.id, n.name, "folder", drive_id)
            for n in self._children(start)
            if n.mime_type == FOLDER
        ]
        return FolderPage(folders)

    async def list_shared_drives(self, token: AccessToken, page_token: str | None) -> FolderPage:
        self._call()
        drives = [DriveFolder(i, name, "shared_drive", i) for i, name in sorted(self.shared_drives.items())]
        return FolderPage(drives)

    def _readable(self, file_id: str) -> FakeNode:
        node = self.nodes.get(file_id)
        if node is None or node.trashed or file_id in self.unavailable:
            raise FileUnavailable("The file could not be read")
        return node

    async def download(self, token: AccessToken, file_id: str) -> bytes:
        self._call()
        node = self._readable(file_id)
        if file_id in self.corrupt:
            return b"%PDF-1.4\nthis is not a real pdf\n"
        return node.content or b""

    async def export_docx(self, token: AccessToken, file_id: str) -> bytes:
        self._call()
        node = self._readable(file_id)
        if (node.size_override or 0) > EXPORT_LIMIT_BYTES:
            raise ExportTooLarge("The Google Doc is larger than Drive's 10 MB export limit")
        if file_id in self.corrupt:
            return b"PK\x03\x04not a real docx"
        return make_docx(node.name, node.paragraphs)


_SHARED: FakeDriveClient | None = None


def shared_fake() -> FakeDriveClient:
    global _SHARED
    if _SHARED is None:
        _SHARED = FakeDriveClient()
    return _SHARED
