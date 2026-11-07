"""Phone numbers (010): routes inbound SIP calls, blocks deleting agents in use and drains deleted
numbers and WhatsApp channels."""

from __future__ import annotations

from arq import cron

from app.agents import hooks as agent_hooks
from app.calls import ports
from app.core.feature import Feature, Runtime
from app.phone_numbers.jobs import drain_channels
from app.phone_numbers.router import router
from app.phone_numbers.routing import PhoneNumberRouter
from app.phone_numbers.service import attachments_for_agent


def install(runtime: Runtime) -> None:
    ports.register_inbound_router(
        "sip_inbound", PhoneNumberRouter(runtime.db, runtime.settings, runtime.http)
    )
    agent_hooks.register_usage_checker(attachments_for_agent)


FEATURE = Feature(
    "phone_numbers",
    routers=(router,),
    install=install,
    jobs={"drain_channels": drain_channels},
    # 010 R8.
    crons=(cron(drain_channels, second={5, 35}, run_at_startup=False, unique=True),),
    id_prefixes=frozenset({"num"}),
    secret_fields=("auth_password",),
)
