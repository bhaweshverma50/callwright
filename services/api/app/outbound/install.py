"""Outbound calls and the do-not-call list (010); supplies 003's outbound dial provider."""

from __future__ import annotations

from app.calls import ports
from app.core.feature import Feature, Runtime
from app.outbound.router import router
from app.outbound.service import SipOutboundDial


def install(runtime: Runtime) -> None:
    ports.set_outbound_dial_provider(SipOutboundDial())


FEATURE = Feature("outbound", routers=(router,), install=install, id_prefixes=frozenset({"dnc"}))
