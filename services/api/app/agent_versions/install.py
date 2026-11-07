"""Agent versions (002); the source of the versions 003 admits and claims calls with."""

from __future__ import annotations

from app.agent_versions import runtime_port
from app.agent_versions.router import router
from app.core.feature import Feature, Runtime


def install(runtime: Runtime) -> None:
    runtime_port.register()


FEATURE = Feature("agent_versions", routers=(router,), install=install, id_prefixes=frozenset({"agv"}))
