"""What a Drive listing means against the files a source already knows (022 research R1, R2).

Pure: no I/O. ``plan`` sorts every listed item and every known file into exactly one bucket:

* ``adds``: supported files the source has not imported (new, or previously skipped or failed
  without a document).
* ``updates``: imported files whose change markers moved (``md5Checksum`` or size for binary
  files, ``version`` for Google Docs). The sync then checks bytes and text before processing.
* ``renames``: imported files with the same markers but a new name or folder path.
* ``unchanged``: imported files with nothing new.
* ``skips``: listed files that are not imported, with the reason.
* ``removals``: imported files missing from the listing (deleted, trashed or moved out),
  including ones whose document failed processing. Files the operator kept after a restore are
  never removals.
* ``forgotten``: skipped or failed files without a document that are no longer listed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.knowledge.models import SourceFile
from app.knowledge.sources.drive import SUPPORTED_MIME_TYPES, DriveItem

MAX_FILE_BYTES = 20 * 1024 * 1024
IMPORTED = frozenset({"synced", "kept"})


@dataclass
class SyncPlan:
    adds: list[DriveItem] = field(default_factory=list)
    updates: list[tuple[DriveItem, SourceFile]] = field(default_factory=list)
    renames: list[tuple[DriveItem, SourceFile]] = field(default_factory=list)
    unchanged: list[SourceFile] = field(default_factory=list)
    skips: list[tuple[DriveItem, str]] = field(default_factory=list)
    removals: list[SourceFile] = field(default_factory=list)
    forgotten: list[SourceFile] = field(default_factory=list)


def skip_reason(item: DriveItem) -> str | None:
    if item.is_shortcut:
        return "shortcut"
    if item.mime_type not in SUPPORTED_MIME_TYPES:
        return "unsupported_type"
    if item.size is not None and item.size > MAX_FILE_BYTES:
        return "too_large"
    return None


def markers_changed(item: DriveItem, known: SourceFile) -> bool:
    if item.is_google_doc:
        return item.version != known.drive_version
    return item.md5 != known.md5 or item.size != known.size_bytes


def plan(listing: Iterable[DriveItem], known_files: Iterable[SourceFile]) -> SyncPlan:
    known = {f.drive_file_id: f for f in known_files}
    out = SyncPlan()
    seen: set[str] = set()
    for item in listing:
        seen.add(item.id)
        reason = skip_reason(item)
        if reason is not None:
            out.skips.append((item, reason))
            continue
        current = known.get(item.id)
        if current is None or current.doc_id is None:
            out.adds.append(item)
        elif markers_changed(item, current):
            out.updates.append((item, current))
        elif item.name != current.name or item.path != current.path:
            out.renames.append((item, current))
        else:
            out.unchanged.append(current)
    for file_id, current in known.items():
        if file_id in seen:
            continue
        if current.doc_id is not None and current.state in ("synced", "failed"):
            out.removals.append(current)
        elif current.doc_id is None:
            out.forgotten.append(current)
    return out
