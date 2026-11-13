"""Erasing accounts whose deletion grace period is over (hourly job).

One account at a time, each step safe to repeat, so a failure part way leaves the account
scheduled and the next run carries on:

1. Skip the account while a call is still active (it is picked up on a later run).
2. Revoke its Google connections at Google (unless another workspace uses the same Google
   account, which a revoke would break).
3. Release phone numbers and WhatsApp channels: SIP objects removed, WhatsApp calling turned
   off (best effort), secrets deleted. A SIP failure stops the account for a retry.
4. Delete uploaded files (knowledge documents, ambient audio) and call recordings from object
   storage. A refusal stops the account for a retry.
5. Delete the identity provider user.
6. ``app_erase_workspace`` (migration s024_0001) deletes every workspace row of every tenant
   table in one transaction, blanks the workspace into a tombstone and deletes the ``users`` row.

Kept on purpose: the billing ledger (``credit_transactions``, ``usage_events``,
``checkout_sessions``, ``call_costs``) under the tombstone workspace id, which holds no email or
name; and the one-trial-per-mailbox claim, which lives in Redis (``trial_claimed:*``) and is not
touched here, so signing up again with the same email gets no new trial credit.

Logs carry counts and opaque ids, never emails, names or phone numbers.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from callwright_contract.calls import ACTIVE_STATUSES
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.idp import IdentityProvider, IdpError
from app.channels.phone_numbers import service as numbers
from app.channels.phone_numbers.models import PhoneNumber
from app.channels.shared import remove_sip_objects
from app.channels.sip import SipError, SipGateway
from app.channels.whatsapp import service as whatsapp
from app.channels.whatsapp.graph_client import GraphError, WhatsAppGraph
from app.channels.whatsapp.models import WhatsAppChannel
from app.connectors.models import Connection
from app.core import storage as core_storage
from app.core.config import Settings
from app.core.db import Database
from app.core.secrets import KeyWrapper, get_secret, key_wrapper
from app.core.storage import ObjectStore
from app.knowledge.sources.drive import DriveClient

logger = logging.getLogger(__name__)

BATCH = 20


@dataclass
class EraseDeps:
    db: Database
    settings: Settings
    store: ObjectStore
    sip: SipGateway
    drive: DriveClient
    graph: WhatsAppGraph
    idp: IdentityProvider
    delete_recordings: Callable[[Sequence[str]], Awaitable[None]]
    wrapper: KeyWrapper


class Deferred(Exception):
    """The account cannot be erased right now; the next run tries again."""


async def _active_calls(session: AsyncSession) -> int:
    row = await session.execute(
        text("select count(*) from calls where status::text = any(:statuses)"),
        {"statuses": list(ACTIVE_STATUSES)},
    )
    return int(row.scalar_one())


async def _revoke_google(deps: EraseDeps, workspace_id: str) -> int:
    """Revoke each connection's refresh token at Google unless another workspace still uses the
    same Google account. Best effort, like removing a connection: the secret goes either way."""
    tokens: list[str] = []
    async with deps.db.transaction(workspace_id=workspace_id) as session:
        connections = (await session.execute(select(Connection))).scalars().all()
        mine: dict[str, int] = {}
        for conn in connections:
            mine[conn.account_subject] = mine.get(conn.account_subject, 0) + 1
        for conn in connections:
            total = int(
                (
                    await session.execute(
                        text("select google_account_connections(:s)"), {"s": conn.account_subject}
                    )
                ).scalar_one()
                or 0
            )
            if total > mine[conn.account_subject]:
                continue
            token = await get_secret(session, deps.wrapper, workspace_id, conn.secret_name)
            if token:
                tokens.append(token)
    for token in tokens:
        try:
            await deps.drive.revoke(token)
        except Exception:
            logger.warning("could not revoke a Google token during account erase", exc_info=True)
    return len(connections)


async def _release_channels(deps: EraseDeps, workspace_id: str) -> int:
    released = 0
    async with deps.db.transaction(workspace_id=workspace_id) as session:
        number_ids = list(
            (await session.execute(select(PhoneNumber.id).where(PhoneNumber.deleted_at.is_(None)))).scalars()
        )
        channel_ids = list(
            (
                await session.execute(select(WhatsAppChannel.id).where(WhatsAppChannel.deleted_at.is_(None)))
            ).scalars()
        )
    for number_id in number_ids:
        async with deps.db.transaction(workspace_id=workspace_id) as session:
            number = await session.get(PhoneNumber, number_id, with_for_update=True)
            if number is None or number.deleted_at is not None:
                continue
            try:
                await remove_sip_objects(deps.sip, number)
            except SipError as exc:
                raise Deferred("phone number routing could not be removed") from exc
            await numbers.finish_delete(session, number)
            released += 1
    for channel_id in channel_ids:
        async with deps.db.transaction(workspace_id=workspace_id) as session:
            channel = await session.get(WhatsAppChannel, channel_id, with_for_update=True)
            if channel is None or channel.deleted_at is not None:
                continue
            token = (
                await get_secret(session, deps.wrapper, workspace_id, channel.access_token_secret)
                if channel.access_token_secret
                else None
            )
            if token:
                try:
                    await deps.graph.disable_calling(
                        token, channel.graph_api_version, channel.meta_phone_number_id
                    )
                except GraphError as exc:
                    logger.warning("could not turn off WhatsApp calling during erase: %s", exc.kind)
            try:
                await remove_sip_objects(deps.sip, channel)
            except SipError as exc:
                raise Deferred("WhatsApp channel routing could not be removed") from exc
            await whatsapp.finish_delete(session, channel)
            released += 1
    return released


async def _delete_files(deps: EraseDeps, workspace_id: str) -> int:
    async with deps.db.transaction(workspace_id=workspace_id) as session:
        uploads = list(
            (
                await session.execute(
                    text(
                        "select storage_key from kb_documents where storage_key is not null "
                        "union select storage_key from ambient_audio_files where storage_key is not null"
                    )
                )
            ).scalars()
        )
        recordings = list(
            (
                await session.execute(text("select recording_key from calls where recording_key is not null"))
            ).scalars()
        )
    try:
        for key in uploads:
            await deps.store.delete(key)
        await deps.delete_recordings(recordings)
    except Exception as exc:
        raise Deferred(f"stored files could not be deleted ({type(exc).__name__})") from exc
    return len(uploads) + len(recordings)


async def erase_account(
    deps: EraseDeps, user_id: str, workspace_id: str | None, subject: str
) -> dict[str, Any]:
    """Erase one account; raises ``Deferred`` when it must wait for the next run."""
    workspace = workspace_id or ""
    stats: dict[str, Any] = {}
    if workspace_id:
        async with deps.db.transaction(workspace_id=workspace_id) as session:
            if await _active_calls(session):
                raise Deferred("a call is still active")
        stats["google_connections"] = await _revoke_google(deps, workspace_id)
        stats["channels_released"] = await _release_channels(deps, workspace_id)
        stats["files"] = await _delete_files(deps, workspace_id)
    try:
        await deps.idp.delete_user(subject)
    except IdpError as exc:
        raise Deferred(f"identity provider user could not be deleted ({type(exc).__name__})") from exc
    async with deps.db.admin_transaction() as session:
        counts = (
            await session.execute(
                text("select app_erase_workspace(:ws, :uid)"), {"ws": workspace, "uid": user_id}
            )
        ).scalar_one()
    stats["rows"] = sum(int(n) for n in counts.values())
    stats["tables"] = len(counts)
    return stats


async def erase_due(deps: EraseDeps, limit: int = BATCH) -> dict[str, int]:
    """Erase every account whose grace period is over, one at a time in its own transaction(s)."""
    async with deps.db.admin_transaction() as session:
        due = (await session.execute(text("select * from account_erasure_due(:n)"), {"n": limit})).all()
    erased = deferred = failed = 0
    for row in due:
        try:
            stats = await erase_account(deps, row.user_id, row.workspace_id, row.idp_subject)
        except Deferred as exc:
            deferred += 1
            logger.warning("account erase deferred for workspace %s: %s", row.workspace_id, exc)
        except Exception:
            failed += 1
            logger.exception("account erase failed for workspace %s", row.workspace_id)
        else:
            erased += 1
            logger.info("account erased: workspace=%s %s", row.workspace_id, stats)
    return {"due": len(due), "erased": erased, "deferred": deferred, "failed": failed}


async def erase_due_accounts(ctx: dict[str, Any]) -> dict[str, int]:
    """arq job."""
    from app.auth.idp import build_idp
    from app.channels.whatsapp.graph_client import build_graph
    from app.knowledge.sources import drive_client

    settings: Settings = ctx["settings"]
    graph = build_graph(settings)
    try:
        deps = EraseDeps(
            db=ctx["db"],
            settings=settings,
            store=ctx["store"],
            sip=ctx["sip"],
            drive=drive_client(),
            graph=graph,
            idp=build_idp(settings, ctx["db"]),
            delete_recordings=functools.partial(core_storage.delete_recordings, settings),
            wrapper=key_wrapper(settings),
        )
        return await erase_due(deps)
    finally:
        await graph.aclose()
