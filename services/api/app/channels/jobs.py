"""Drain cleanup cron (010 T041, research R8): every 30 s, numbers and WhatsApp channels in
``draining`` with no active call lose their SIP objects and are soft-deleted. A SIP failure
leaves the row draining for the next run; new calls are already refused."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.calls.models import Call
from app.channels.phone_numbers import service as numbers
from app.channels.phone_numbers.models import PhoneNumber
from app.channels.shared import active_counts, finish_or_drain
from app.channels.sip import SipGateway
from app.channels.whatsapp import service as whatsapp
from app.channels.whatsapp.models import WhatsAppChannel
from app.core.db import Database

logger = logging.getLogger(__name__)

# ``channels_draining()`` kind: the row, its column on ``calls`` and how its delete finishes.
KINDS: dict[str, tuple[Any, Any, Any]] = {
    "phone_number": (PhoneNumber, Call.phone_number_id, numbers.finish_delete),
    "whatsapp_channel": (WhatsAppChannel, Call.whatsapp_channel_id, whatsapp.finish_delete),
}


async def drain_channels_once(db: Database, sip: SipGateway) -> int:
    """Finish every idle draining number and channel; returns how many were deleted."""
    async with db.transaction() as session:
        rows = (await session.execute(text("select kind, id, workspace_id from channels_draining()"))).all()
    done = 0
    for row in rows:
        model, column, finish = KINDS[row.kind]
        async with db.transaction(workspace_id=row.workspace_id) as session:
            channel = await session.get(model, row.id, with_for_update=True)
            if channel is None or channel.status != "draining":
                continue
            if (await active_counts(session, column, [channel.id])).get(channel.id):
                continue
            if await finish_or_drain(sip, session, channel, finish):
                done += 1
    if done:
        logger.info("drain cleanup removed %d channel(s)", done)
    return done


async def drain_channels(ctx: dict[str, Any]) -> int:
    return await drain_channels_once(ctx["db"], ctx["sip"])
