"""Flow agents (004); see ``flows/hooks.py`` for what it registers with 002, 003 and 005."""

from __future__ import annotations

from app.core.feature import Feature, Runtime
from app.flows import assistant_fake, hooks
from app.flows.router import router


def install(runtime: Runtime) -> None:
    hooks.register()
    assistant_fake.register_fakes()


FEATURE = Feature("flows", routers=(router,), install=install, id_prefixes=frozenset({"flw"}))
