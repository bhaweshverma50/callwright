"""SIP specifics. Ring phase and outbound dialling are delivered by 010 (010 T020, T033).

Only what the 003 job entry needs is implemented here: reading the SIP participant attributes
for the claim and mapping keypad digits to RFC 4733 event codes for ``publish_dtmf``. The rest
are stubs with the signatures 010 fills in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.internal_api import OutboundDial, SipAttributes

# LiveKit SIP participant attribute names.
SIP_ATTR_CALL_ID = "sip.callID"
SIP_ATTR_TRUNK_ID = "sip.trunkID"
SIP_ATTR_TRUNK_NUMBER = "sip.trunkPhoneNumber"
SIP_ATTR_CALLER_NUMBER = "sip.phoneNumber"

DTMF_CODES: Mapping[str, int] = {**{str(d): d for d in range(10)}, "*": 10, "#": 11}


class TelephonyUnavailable(Exception):
    """Raised by the stubs until 010 registers the SIP implementation."""

    diagnostic = "telephony-unavailable"


def sip_attributes(attributes: Mapping[str, str], identity: str | None = None) -> SipAttributes:
    """Claim ``sip`` block from a SIP participant's attributes (contract ``SipAttributes``)."""
    return SipAttributes(
        call_id=attributes.get(SIP_ATTR_CALL_ID),
        trunk_id=attributes.get(SIP_ATTR_TRUNK_ID),
        trunk_phone_number=attributes.get(SIP_ATTR_TRUNK_NUMBER),
        caller_number=attributes.get(SIP_ATTR_CALLER_NUMBER),
        participant_identity=identity,
    )


def dtmf_code(digit: str) -> int:
    try:
        return DTMF_CODES[digit]
    except KeyError:
        raise ValueError(f"invalid keypad digit {digit!r}") from None


async def ring_phase(room: Any, ring_duration_ms: int) -> None:
    """Inbound ring before answering (FR-017). Implemented by 010."""
    raise TelephonyUnavailable("inbound ring phase is delivered by 010-channels")


async def dial_outbound(ctx: Any, dial: OutboundDial) -> Any:
    """Place an outbound SIP call and wait for answer. Implemented by 010."""
    raise TelephonyUnavailable("outbound dialling is delivered by 010-channels")
