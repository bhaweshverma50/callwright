"""Drain cleanup cron (010 T041, research R8): every 30 s, numbers and WhatsApp channels in
``draining`` with no active call lose their SIP objects and are soft-deleted. A SIP failure
leaves the row draining for the next run; new calls are already refused."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.calls.models import Call
from app.core.db import Database
from app.phone_numbers import provisioning
from app.phone_numbers import service as numbers
from app.phone_numbers.models import PhoneNumber
from app.phone_numbers.shared import active_counts
from app.phone_numbers.sip import SipError, SipGateway
from app.whatsapp import service as whatsapp
from app.whatsapp.models import WhatsAppChannel

logger = logging.getLogger(__name__)


async def drain_channels_once(db: Database, sip: SipGateway) -> int:
    """Finish every idle draining number and channel; returns how many were deleted."""
    async with db.transaction() as session:
        rows = (await session.execute(text("select kind, id, workspace_id from channels_draining()"))).all()
    done = 0
    for row in rows:
        async with db.transaction(workspace_id=row.workspace_id) as session:
            if row.kind == "phone_number":
                number = await session.get(PhoneNumber, row.id, with_for_update=True)
                if number is None or number.status != "draining":
                    continue
                if (await active_counts(session, Call.phone_number_id, [number.id])).get(number.id):
                    continue
                try:
                    await provisioning.remove_all(sip, number)
                except SipError as exc:
                    number.status_detail = f"Cleanup pending: {exc}"[:500]
                    continue
                await numbers.finish_delete(session, number)
            else:
                channel = await session.get(WhatsAppChannel, row.id, with_for_update=True)
                if channel is None or channel.status != "draining":
                    continue
                if (await active_counts(session, Call.whatsapp_channel_id, [channel.id])).get(channel.id):
                    continue
                try:
                    if channel.lk_dispatch_rule_id:
                        await sip.delete_dispatch_rule(channel.lk_dispatch_rule_id)
                    if channel.lk_inbound_trunk_id:
                        await sip.delete_trunk(channel.lk_inbound_trunk_id)
                except SipError as exc:
                    channel.status_detail = f"Cleanup pending: {exc}"[:500]
                    continue
                await whatsapp.finish_delete(session, channel)
            done += 1
    if done:
        logger.info("drain cleanup removed %d channel(s)", done)
    return done


async def drain_channels(ctx: dict[str, Any]) -> int:
    return await drain_channels_once(ctx["db"], ctx["sip"])
