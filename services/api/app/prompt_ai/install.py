"""Prompt assistant (002)."""

from __future__ import annotations

from app.core.feature import Feature, Runtime
from app.prompt_ai import fake
from app.prompt_ai.router import router


def install(runtime: Runtime) -> None:
    fake.register_fakes()


FEATURE = Feature("prompt_ai", routers=(router,), install=install)
