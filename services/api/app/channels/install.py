"""Channels (010): phone numbers and WhatsApp channels. Routes inbound SIP and WhatsApp calls,
supplies the outbound dial, blocks deleting agents a channel uses and drains deleted channels."""

from __future__ import annotations

from arq import cron

from app.agents import hooks as agent_hooks
from app.calls import ports
from app.channels.dial import SipOutboundDial
from app.channels.jobs import drain_channels
from app.channels.phone_numbers import service as numbers
from app.channels.phone_numbers.router import router as numbers_router
from app.channels.routing import PhoneNumberRouter, WhatsAppRouter
from app.channels.whatsapp import service as whatsapp
from app.channels.whatsapp.router import public_router as whatsapp_public_router
from app.channels.whatsapp.router import router as whatsapp_router
from app.core.feature import Feature, Runtime


def install(runtime: Runtime) -> None:
    ports.register_inbound_router(
        "sip_inbound", PhoneNumberRouter(runtime.db, runtime.settings, runtime.http)
    )
    ports.register_inbound_router("whatsapp", WhatsAppRouter(runtime.db, runtime.settings, runtime.http))
    ports.set_outbound_dial_provider(SipOutboundDial())
    agent_hooks.register_usage_checker(numbers.attachments_for_agent)
    agent_hooks.register_usage_checker(whatsapp.attachments_for_agent)


FEATURE = Feature(
    "channels",
    routers=(numbers_router, whatsapp_router, whatsapp_public_router),
    install=install,
    jobs={"drain_channels": drain_channels},
    # 010 R8.
    crons=(cron(drain_channels, second={5, 35}, run_at_startup=False, unique=True),),
    id_prefixes=frozenset({"num", "wa", "wcr"}),
    secret_fields=("auth_password", "verify_token", "hub.verify_token", "app_secret", "sip_user_password"),
)
