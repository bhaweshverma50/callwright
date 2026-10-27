"""Human labels (007 T045; FR-021, FR-022): set, change and remove the viewer's one label per call."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation
from app.calls.models import Call
from app.core.errors import field_error, not_found, validation_failed
from app.core.ids import new_id

NOTE_MAX = 2000


def display_name(email: str) -> str:
    return email.split("@")[0] if email else "Teammate"


def view(a: Annotation) -> dict[str, Any]:
    return {
        "id": a.id,
        "call_id": a.call_id,
        "user": {"id": a.user_id, "display_name": a.user_display_name or "Teammate"},
        "label": a.label,
        "note": a.note,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


async def require_call(session: AsyncSession, call_id: str) -> Call:
    call = await session.get(Call, call_id)
    if call is None:
        raise not_found("call")
    return call


async def list_for_call(session: AsyncSession, call_id: str, user_id: str) -> dict[str, Any]:
    await require_call(session, call_id)
    rows = list(
        (
            await session.execute(
                select(Annotation).where(Annotation.call_id == call_id).order_by(Annotation.updated_at.desc())
            )
        ).scalars()
    )
    mine = next((a for a in rows if a.user_id == user_id), None)
    ordered = ([mine] if mine else []) + [a for a in rows if a is not mine]
    return {"mine": view(mine) if mine else None, "items": [view(a) for a in ordered]}


async def put_mine(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    email: str,
    call_id: str,
    label: str,
    note: str | None,
) -> Annotation:
    await require_call(session, call_id)
    if note is not None and len(note) > NOTE_MAX:
        raise validation_failed(
            [field_error("/note", "out_of_range", "Keep the note under 2,000 characters")]
        )
    note = note.strip() or None if note is not None else None
    now = datetime.now(UTC)
    await session.execute(
        text(
            "insert into annotations (id, workspace_id, call_id, user_id, user_display_name, label, note, "
            "created_at, updated_at) values (:id, :ws, :call, :user, :name, :label, :note, :now, :now) "
            "on conflict (call_id, user_id) do update set label = excluded.label, note = excluded.note, "
            "user_display_name = excluded.user_display_name, updated_at = excluded.updated_at"
        ),
        {
            "id": new_id("ann"),
            "ws": workspace_id,
            "call": call_id,
            "user": user_id,
            "name": display_name(email),
            "label": label,
            "note": note,
            "now": now,
        },
    )
    row = (
        await session.execute(
            select(Annotation)
            .where(Annotation.call_id == call_id, Annotation.user_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return row


async def delete_mine(session: AsyncSession, call_id: str, user_id: str) -> None:
    await require_call(session, call_id)
    await session.execute(
        delete(Annotation).where(Annotation.call_id == call_id, Annotation.user_id == user_id)
    )
