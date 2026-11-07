"""WhatsApp channels (010): routes inbound WhatsApp calls and blocks deleting agents in use."""

from __future__ import annotations

from app.agents import hooks as agent_hooks
from app.calls import ports
from app.core.feature import Feature, Runtime
from app.whatsapp.router import public_router, router
from app.whatsapp.routing import WhatsAppRouter
from app.whatsapp.service import attachments_for_agent


def install(runtime: Runtime) -> None:
    ports.register_inbound_router("whatsapp", WhatsAppRouter(runtime.db, runtime.settings, runtime.http))
    agent_hooks.register_usage_checker(attachments_for_agent)


FEATURE = Feature(
    "whatsapp",
    routers=(router, public_router),
    install=install,
    id_prefixes=frozenset({"wa", "wcr"}),
    secret_fields=("verify_token", "hub.verify_token", "app_secret", "sip_user_password"),
)
