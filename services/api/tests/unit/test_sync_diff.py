"""The sync diff (022 T034, T053): what a listing means against the files a source already knows."""

from __future__ import annotations

from app.knowledge.models import SourceFile
from app.knowledge.sources import diff
from app.knowledge.sources.drive import DOCX, GOOGLE_DOC, PDF, SHORTCUT, DriveItem

SHEET = "application/vnd.google-apps.spreadsheet"
MB = 1024 * 1024


def item(file_id: str, mime: str = GOOGLE_DOC, **kw: object) -> DriveItem:
    return DriveItem(id=file_id, name=str(kw.pop("name", file_id)), mime_type=mime, **kw)  # type: ignore[arg-type]


def known(file_id: str, **kw: object) -> SourceFile:
    values: dict[str, object] = {
        "id": f"f-{file_id}",
        "workspace_id": "ws",
        "source_id": "src",
        "drive_file_id": file_id,
        "name": file_id,
        "path": "",
        "mime_type": GOOGLE_DOC,
        "state": "synced",
        "doc_id": f"doc-{file_id}",
        "drive_version": "1",
    }
    values.update(kw)
    return SourceFile(**values)


def test_new_supported_files_are_adds_and_others_are_skipped() -> None:
    listing = [
        item("a"),
        item("b", PDF, size=10, md5="m"),
        item("c", DOCX, size=10, md5="m"),
        item("d", SHEET),
        item("e", SHORTCUT),
        item("f", PDF, size=30 * MB, md5="m"),
        item("g", "image/png", size=10),
    ]
    plan = diff.plan(listing, [])
    assert [i.id for i in plan.adds] == ["a", "b", "c"]
    assert {(i.id, reason) for i, reason in plan.skips} == {
        ("d", "unsupported_type"),
        ("e", "shortcut"),
        ("f", "too_large"),
        ("g", "unsupported_type"),
    }
    assert plan.removals == [] and plan.updates == [] and plan.renames == []


def test_a_previously_skipped_file_that_becomes_supported_is_added() -> None:
    plan = diff.plan([item("a")], [known("a", state="skipped", reason="unsupported_type", doc_id=None)])
    assert [i.id for i in plan.adds] == ["a"]


def test_unchanged_renamed_and_moved_files() -> None:
    plan = diff.plan(
        [
            item("a", version="1"),
            item("b", version="1", name="New name"),
            item("c", version="1", path="Moved"),
        ],
        [known("a"), known("b"), known("c")],
    )
    assert [k.drive_file_id for k in plan.unchanged] == ["a"]
    assert sorted(k.drive_file_id for _, k in plan.renames) == ["b", "c"]
    assert plan.updates == []


def test_changed_markers_are_updates() -> None:
    plan = diff.plan(
        [item("a", version="2"), item("b", PDF, size=10, md5="new"), item("c", PDF, size=11, md5="m")],
        [
            known("a"),
            known("b", mime_type=PDF, md5="old", size_bytes=10),
            known("c", mime_type=PDF, md5="m", size_bytes=10),
        ],
    )
    assert sorted(k.drive_file_id for _, k in plan.updates) == ["a", "b", "c"]


def test_missing_files_are_removals_except_kept_ones() -> None:
    plan = diff.plan(
        [],
        [
            known("a"),
            known("b", state="kept"),
            known("c", state="skipped", reason="unsupported_type", doc_id=None),
        ],
    )
    assert [k.drive_file_id for k in plan.removals] == ["a"]
    assert [k.drive_file_id for k in plan.forgotten] == ["c"]


def test_a_kept_file_that_returns_is_synced_again() -> None:
    plan = diff.plan([item("b", version="1")], [known("b", state="kept")])
    assert [k.drive_file_id for k in plan.unchanged] == ["b"]
    assert plan.removals == []
