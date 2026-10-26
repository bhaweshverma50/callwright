"""Workspace do-not-call list (010 T075, FR-035).

Every number is stored once per workspace in E.164 (``phonenumbers``; national formats use the
``default_region`` chosen at entry or import time). CSV imports (UTF-8, header row with a
``number`` column and an optional ``note`` column, at most 100,000 data rows and 10 MB) store
valid numbers with ``INSERT ... ON CONFLICT DO NOTHING``, count duplicates in the file and
already listed, and report invalid rows (the first 1,000) without failing the import.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, not_found
from app.core.ids import new_id
from app.core.pagination import page_meta
from app.outbound.models import DncEntry
from app.phone_numbers import validation

MAX_ENTRIES = 1_000_000
MAX_ROWS = 100_000
MAX_BYTES = 10 * 1024 * 1024
MAX_REPORTED = 1_000
MAX_NOTE = 200
BATCH = 2_000  # 8 columns per row stays under the 32,767 bind parameter limit


class CsvError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail

    def problem(self) -> ProblemError:
        title = "File too large" if self.status == 413 else "Invalid CSV"
        return ProblemError(self.status, self.code, title, self.detail)


@dataclass
class ParsedCsv:
    rows: int = 0
    numbers: dict[str, str | None] = field(default_factory=dict)  # e164 -> note, first wins
    duplicates_in_file: int = 0
    invalid: list[dict[str, Any]] = field(default_factory=list)
    invalid_count: int = 0


def parse_csv(data: bytes, default_region: str | None = None) -> ParsedCsv:
    if len(data) > MAX_BYTES:
        raise CsvError(413, "file_too_large", "The file is over 10 MB. Split it and import each part.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvError(
            422, "invalid_csv", "The file is not UTF-8 text. Save it as CSV UTF-8 and retry."
        ) from None
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    columns = [h.strip().lower() for h in header or []]
    if "number" not in columns:
        raise CsvError(422, "invalid_csv", "The first row must be a header with a 'number' column.")
    number_at = columns.index("number")
    note_at = columns.index("note") if "note" in columns else None
    out = ParsedCsv()
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        out.rows += 1
        if out.rows > MAX_ROWS:
            raise CsvError(413, "file_too_large", "The file has more than 100,000 rows. Split it and retry.")
        value = row[number_at].strip() if number_at < len(row) else ""
        note = row[note_at].strip() if note_at is not None and note_at < len(row) else ""
        error = None
        e164 = ""
        try:
            e164 = validation.normalize_number(value, default_region)
        except validation.InvalidValue as exc:
            error = str(exc)
        if error is None and len(note) > MAX_NOTE:
            error = "The note is longer than 200 characters."
        if error is not None:
            out.invalid_count += 1
            if len(out.invalid) < MAX_REPORTED:
                out.invalid.append({"row": out.rows, "value": value[:64], "error": error})
            continue
        if e164 in out.numbers:
            out.duplicates_in_file += 1
            continue
        out.numbers[e164] = note or None
    return out


def to_out(entry: DncEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "number": entry.e164,
        "note": entry.note,
        "source": entry.source,
        "created_by_user_id": entry.created_by_user_id,
        "created_at": entry.created_at.isoformat(),
    }


async def _count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(DncEntry))).scalar_one())


async def list_entries(
    session: AsyncSession, *, page: int, page_size: int, number: str | None
) -> dict[str, Any]:
    query = select(DncEntry)
    if number:
        prefix = "".join(ch for ch in number if ch.isdigit() or ch == "+")
        if prefix and not prefix.startswith("+"):
            prefix = "+" + prefix
        query = query.where(DncEntry.e164.startswith(prefix, autoescape=True))
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = (
        await session.execute(
            query.order_by(DncEntry.created_at.desc(), DncEntry.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()
    return {"items": [to_out(e) for e in rows], **page_meta(total, page, page_size)}


async def find(session: AsyncSession, e164: str) -> DncEntry | None:
    return (await session.execute(select(DncEntry).where(DncEntry.e164 == e164))).scalar_one_or_none()


async def add_entry(
    session: AsyncSession,
    workspace_id: str,
    user_id: str | None,
    number: str,
    default_region: str | None,
    note: str | None,
) -> DncEntry:
    try:
        e164 = validation.normalize_number(number, default_region)
    except validation.InvalidValue as exc:
        raise ProblemError(422, "invalid_number", "Invalid number", str(exc)) from None
    existing = await find(session, e164)
    if existing is not None:
        raise ProblemError(
            409, "dnc_entry_exists", "Already listed", f"{e164} is already on the list as {existing.id}."
        )
    if await _count(session) >= MAX_ENTRIES:
        raise ProblemError(
            409, "dnc_limit_reached", "List is full", "The do-not-call list holds 1,000,000 numbers."
        )
    entry = DncEntry(
        id=new_id("dnc"),
        workspace_id=workspace_id,
        e164=e164,
        note=(note or "").strip() or None,
        source="manual",
        created_by_user_id=user_id,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    try:
        await session.flush()
    except IntegrityError:
        raise ProblemError(
            409, "dnc_entry_exists", "Already listed", f"{e164} is already on the list."
        ) from None
    return entry


async def remove_entry(session: AsyncSession, dnc_id: str) -> None:
    entry = await session.get(DncEntry, dnc_id)
    if entry is None:
        raise not_found("do-not-call entry")
    await session.delete(entry)
    await session.flush()


async def import_csv(
    session: AsyncSession, workspace_id: str, user_id: str | None, parsed: ParsedCsv
) -> dict[str, Any]:
    existing = await _count(session)
    if existing + len(parsed.numbers) > MAX_ENTRIES:
        already = 0
        numbers = list(parsed.numbers)
        for start in range(0, len(numbers), BATCH):
            chunk = numbers[start : start + BATCH]
            already += int(
                (
                    await session.execute(
                        select(func.count()).select_from(DncEntry).where(DncEntry.e164.in_(chunk))
                    )
                ).scalar_one()
            )
        if existing + len(parsed.numbers) - already > MAX_ENTRIES:
            raise ProblemError(
                409,
                "dnc_limit_reached",
                "List is full",
                "This import would take the list over 1,000,000 numbers.",
            )
    batch_id = new_id("dnc")
    now = datetime.now(UTC)
    imported = 0
    items = list(parsed.numbers.items())
    for start in range(0, len(items), BATCH):
        values = [
            {
                "id": new_id("dnc"),
                "workspace_id": workspace_id,
                "e164": e164,
                "note": note,
                "source": "csv_import",
                "import_batch_id": batch_id,
                "created_by_user_id": user_id,
                "created_at": now,
            }
            for e164, note in items[start : start + BATCH]
        ]
        result = await session.execute(
            insert(DncEntry).values(values).on_conflict_do_nothing().returning(DncEntry.id)
        )
        imported += len(result.all())
    return {
        "rows": parsed.rows,
        "imported": imported,
        "duplicates": parsed.duplicates_in_file + (len(items) - imported),
        "invalid_count": parsed.invalid_count,
        "invalid": parsed.invalid,
    }
