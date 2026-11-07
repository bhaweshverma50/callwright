"""003's ``OutboundDialProvider`` (010 T032): what a ``sip_outbound`` claim dials, the number's
outbound trunk, the two numbers and the ring timeout stored on the call."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.ports import OutboundDial
from app.channels.phone_numbers.models import PhoneNumber


class SipOutboundDial:
    async def dial_spec(self, session: AsyncSession, call: Any) -> OutboundDial | None:
        if not call.phone_number_id or not call.to_number or not call.from_number:
            return None
        number = await session.get(PhoneNumber, call.phone_number_id)
        if number is None or number.lk_outbound_trunk_id is None:
            return None
        return OutboundDial(
            sip_trunk_id=number.lk_outbound_trunk_id,
            to_number=call.to_number,
            from_number=call.from_number,
            ring_timeout_s=int(call.ring_timeout_s or 30),
        )
