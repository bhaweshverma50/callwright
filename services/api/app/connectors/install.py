"""Google connections (022): the Connections page routes, and the Drive client both the API and
the jobs worker use for knowledge sources."""

from __future__ import annotations

from app.connectors.router import router
from app.core.feature import Feature, Runtime
from app.knowledge import sources


def install(runtime: Runtime) -> None:
    sources.install(runtime.settings, runtime.http)


FEATURE = Feature(
    "connectors",
    routers=(router,),
    install=install,
    id_prefixes=frozenset({"conn"}),
)
