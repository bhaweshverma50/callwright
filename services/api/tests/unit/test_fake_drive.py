"""The fake Drive behaves like the port promises (022 T005), so the sync tests can trust it."""

from __future__ import annotations

import pytest

from app.knowledge.sources.drive import (
    GOOGLE_DOC,
    AccessToken,
    DriveRoot,
    ExportTooLarge,
    FileUnavailable,
    GoogleTemporary,
    RootUnavailable,
    SourceTooLarge,
    TokenRevoked,
)
from app.knowledge.sources.fake_drive import SHEET, FakeDriveClient

TOKEN = AccessToken("fake-access")


@pytest.fixture
def drive() -> FakeDriveClient:
    return FakeDriveClient()


async def test_clinic_preset_walks_subfolders(drive: FakeDriveClient) -> None:
    root_id = drive.seed("clinic")["Clinic policies"]
    root = await drive.get_root(TOKEN, "folder", root_id, None)
    assert root.name == "Clinic policies"
    items = await drive.list_tree(TOKEN, root, include_subfolders=True)
    names = {i.name for i in items}
    assert "Vaccination drive" in names and "Slots" in names and "Scanned archive.pdf" in names
    assert len(items) == 12
    sub = next(i for i in items if i.name == "Vaccination drive")
    assert sub.path == "2026" and sub.is_google_doc
    flat = await drive.list_tree(TOKEN, root, include_subfolders=False)
    assert "Vaccination drive" not in {i.name for i in flat}


async def test_files_download_and_export(drive: FakeDriveClient) -> None:
    root = drive.add_folder("F")
    doc = drive.add_doc(root, "Doc", ["Hello"])
    pdf = drive.add_pdf(root, "a.pdf", ["Line"])
    assert (await drive.download(TOKEN, pdf)).startswith(b"%PDF-")
    assert (await drive.export_docx(TOKEN, doc)).startswith(b"PK")
    items = {i.id: i for i in await drive.list_tree(TOKEN, DriveRoot("folder", root, "F"), True)}
    assert items[pdf].md5 and items[pdf].size
    assert items[doc].mime_type == GOOGLE_DOC and items[doc].md5 is None


async def test_edit_and_touch_move_the_version(drive: FakeDriveClient) -> None:
    root = drive.add_folder("F")
    doc = drive.add_doc(root, "Doc", ["One"])
    drive.touch(doc)
    drive.edit(doc, ["Two"])
    items = await drive.list_tree(TOKEN, DriveRoot("folder", root, "F"), True)
    assert items[0].version == "3"


async def test_switches_raise_classified_errors(drive: FakeDriveClient) -> None:
    root = drive.add_folder("F")
    doc = drive.add_doc(root, "Doc", ["One"])
    other = drive.add_other(root, "Sheet", SHEET)
    drive.revoked = True
    with pytest.raises(TokenRevoked):
        await drive.refresh("r")
    drive.revoked = False
    drive.unshared.add(root)
    with pytest.raises(RootUnavailable):
        await drive.get_root(TOKEN, "folder", root, None)
    drive.unshared.clear()
    drive.outage = True
    with pytest.raises(GoogleTemporary):
        await drive.list_tree(TOKEN, DriveRoot("folder", root, "F"), True)
    drive.outage = False
    drive.unavailable.add(doc)
    with pytest.raises(FileUnavailable):
        await drive.export_docx(TOKEN, doc)
    drive.nodes[doc].size_override = 11 * 1024 * 1024
    drive.unavailable.clear()
    with pytest.raises(ExportTooLarge):
        await drive.export_docx(TOKEN, doc)
    with pytest.raises(SourceTooLarge):
        await drive.list_tree(TOKEN, DriveRoot("folder", root, "F"), True, max_items=1)
    drive.fail_after_items = 1
    with pytest.raises(GoogleTemporary):
        await drive.list_tree(TOKEN, DriveRoot("folder", root, "F"), True)
    assert other


async def test_shared_drive_and_counter(drive: FakeDriveClient) -> None:
    drive_id = drive.add_shared_drive("Team")
    drive.add_doc(drive_id, "Handbook", ["Rules"])
    root = await drive.get_root(TOKEN, "shared_drive", drive_id, None)
    assert root.drive_id == drive_id
    assert [d.name for d in (await drive.list_shared_drives(TOKEN, None)).items] == ["Team"]
    assert len(await drive.list_tree(TOKEN, root, True)) == 1
    assert drive.calls == 3
