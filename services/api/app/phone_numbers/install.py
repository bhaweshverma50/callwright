"""Registers 010's implementations with 003's extension points (``calls/ports.py``)."""

from __future__ import annotations

from typing import Any

from app.calls.ports import register_inbound_router, set_outbound_dial_provider
from app.outbound.service import SipOutboundDial
from app.phone_numbers.routing import PhoneNumberRouter
from app.whatsapp.routing import WhatsAppRouter


def install(state: Any) -> None:
    """``state`` is ``app.state`` with ``db``, ``settings`` and ``webhook_http`` set."""
    register_inbound_router("sip_inbound", PhoneNumberRouter(state.db, state.settings, state.webhook_http))
    register_inbound_router("whatsapp", WhatsAppRouter(state.db, state.settings, state.webhook_http))
    set_outbound_dial_provider(SipOutboundDial())
