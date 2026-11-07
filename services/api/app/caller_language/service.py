"""Caller language (012): saved languages per caller, the claim's start language, the switch
report from the voice worker and the call view.

A preference belongs to a phone number in a workspace: the caller on inbound phone calls, the
dialled number on outbound calls (callbacks are outbound calls to the person who asked, so they
start in the saved language without anything special). Browser test calls, WhatsApp and
simulated calls never save one. Switches are recorded on every call so the call view can show
them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from callwright_contract.calls import PHONE_CHANNELS
from callwright_contract.values import E164
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.caller_language.models import CallerPreference, CallLanguage
from app.calls.lookups import config_for
from app.calls.models import Call
from app.calls.origins import policy
from app.core.db import Database
from app.core.errors import field_error, not_found, validation_failed
from app.core.ids import new_id
from app.core.pagination import page_meta
from app.voices.catalog import DEFAULT_LANGUAGE
from app.voices.catalog import load_catalog as load_voice_catalog


def label(code: str) -> str:
    lang = load_voice_catalog().language(code)
    return lang.label if lang is not None else code


def ref(code: str) -> dict[str, str]:
    return {"code": code, "label": label(code)}


def number_for(call: Call) -> str | None:
    """The number whose language is saved: the caller (inbound) or the dialled number."""
    if call.channel not in PHONE_CHANNELS:
        return None
    number = call.from_number if call.direction == "inbound" else call.to_number
    return number if number and E164.match(number) else None


def saves_preference(call: Call) -> bool:
    return policy(call.origin).saves_preferences and number_for(call) is not None


async def preference_for(session: AsyncSession, number: str) -> CallerPreference | None:
    return (
        await session.execute(select(CallerPreference).where(CallerPreference.phone_number == number))
    ).scalar_one_or_none()


def preference_out(row: CallerPreference) -> dict[str, Any]:
    return {
        "id": row.id,
        "phone_number": row.phone_number,
        "language": ref(row.preferred_language),
        "updated_at": row.updated_at.isoformat(),
        "last_call_id": row.last_call_id,
    }


async def start_language(
    session: AsyncSession, call: Call, options: Sequence[Mapping[str, Any]]
) -> str | None:
    """``RuntimeConfig.caller_language``: the caller's saved language when the agent offers it
    and it is not the agent's own; recorded once as the call's start language."""
    if len(options) < 2 or not saves_preference(call):
        return None
    number = number_for(call)
    assert number is not None
    pref = await preference_for(session, number)
    if pref is None:
        return None
    codes = [str(o["code"]) for o in options]
    code = pref.preferred_language
    if code not in codes[1:]:
        return None
    exists = (
        await session.execute(
            select(CallLanguage.id).where(CallLanguage.call_id == call.id, CallLanguage.kind == "start")
        )
    ).first()
    if exists is None:
        session.add(
            CallLanguage(
                id=new_id("clg"),
                workspace_id=call.workspace_id,
                call_id=call.id,
                kind="start",
                language=code,
                offset_ms=0,
            )
        )
        await session.flush()
    return code


async def report_switch(
    db: Database,
    workspace_id: str,
    call_id: str,
    language: str,
    offset_ms: int | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    if load_voice_catalog().language(language) is None or language == "multi":
        raise validation_failed(
            [field_error("/language", "not_in_catalog", f"The language {language!r} is not offered.")]
        )
    async with db.transaction(workspace_id=workspace_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            raise not_found("call")
        session.add(
            CallLanguage(
                id=new_id("clg"),
                workspace_id=workspace_id,
                call_id=call_id,
                kind="switch",
                language=language,
                offset_ms=offset_ms,
            )
        )
        if not policy(call.origin).saves_preferences:
            return {"recorded": True, "stored": False, "reason": "simulation"}
        if call.channel not in PHONE_CHANNELS:
            return {"recorded": True, "stored": False, "reason": "not_phone_call"}
        number = number_for(call)
        if number is None:
            return {"recorded": True, "stored": False, "reason": "no_number"}
        pref = await preference_for(session, number)
        if pref is None:
            pref = CallerPreference(
                id=new_id("cpf"), workspace_id=workspace_id, phone_number=number, created_at=now
            )
            session.add(pref)
        pref.preferred_language = language
        pref.last_call_id = call_id
        pref.updated_at = now
        await session.flush()
    return {"recorded": True, "stored": True, "reason": "saved"}


async def list_preferences(
    session: AsyncSession, *, page: int, page_size: int, phone_number: str | None
) -> dict[str, Any]:
    query = select(CallerPreference)
    if phone_number:
        query = query.where(CallerPreference.phone_number == phone_number)
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = (
        (
            await session.execute(
                query.order_by(CallerPreference.updated_at.desc(), CallerPreference.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [preference_out(r) for r in rows], **page_meta(total, page, page_size)}


async def delete_preference(session: AsyncSession, preference_id: str) -> None:
    row = await session.get(CallerPreference, preference_id)
    if row is None:
        raise not_found("caller_preference")
    await session.delete(row)
    await session.flush()


async def call_language(session: AsyncSession, call_id: str) -> dict[str, Any]:
    call = await session.get(Call, call_id)
    if call is None:
        raise not_found("call")
    config = await config_for(session, call) or {}
    agent_code = str(config.get("language") or DEFAULT_LANGUAGE)
    rows = (
        (
            await session.execute(
                select(CallLanguage)
                .where(CallLanguage.call_id == call_id)
                .order_by(CallLanguage.created_at, CallLanguage.id)
            )
        )
        .scalars()
        .all()
    )
    start = next((r for r in rows if r.kind == "start"), None)
    current = start.language if start is not None else agent_code
    switches = []
    for row in rows:
        if row.kind != "switch" or row.language == current:
            continue
        switches.append({"offset_ms": row.offset_ms, "from": ref(current), "to": ref(row.language)})
        current = row.language
    number = number_for(call) if policy(call.origin).saves_preferences else None
    pref = await preference_for(session, number) if number else None
    return {
        "call_id": call_id,
        "agent_language": ref(agent_code),
        "started_language": ref(start.language if start is not None else agent_code),
        "started_from": "saved_preference" if start is not None else "agent",
        "switches": switches,
        "caller_number": number,
        "preference": preference_out(pref) if pref is not None else None,
    }
