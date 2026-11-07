"""Tools (005); registers the ``tool_ids`` validator and ``tools`` snapshot resolver with 002."""

from __future__ import annotations

from app.core.feature import Feature, Runtime
from app.tools import hooks
from app.tools.router import router


def install(runtime: Runtime) -> None:
    hooks.register()


FEATURE = Feature("tools", routers=(router,), install=install, id_prefixes=frozenset({"tool"}))
