"""Agents and their versions (002); the source of the versions 003 admits and claims calls with."""

from __future__ import annotations

from app.agents import checks
from app.agents.router import router
from app.agents.versions_router import router as versions_router
from app.core.feature import Feature, Runtime
from app.voices import service as voices


def install(runtime: Runtime) -> None:
    voices.set_ambient_usage(checks.ambient_in_use)


FEATURE = Feature(
    "agents", routers=(router, versions_router), install=install, id_prefixes=frozenset({"agt", "agv"})
)
