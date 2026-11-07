"""Model catalog (002) and the model runtime the post-call and testing features share."""

from __future__ import annotations

from app.core.feature import Feature, Runtime
from app.llms import runtime as model_runtime
from app.llms.router import router


def install(runtime: Runtime) -> None:
    model_runtime.install(runtime.settings, queue=runtime.queue)


FEATURE = Feature("llms", routers=(router,), install=install)
