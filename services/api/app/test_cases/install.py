"""Test cases (008): routes and offline fake replies for test case drafting."""

from __future__ import annotations

from app.core.feature import Feature, Runtime
from app.test_cases import generate
from app.test_cases.router import router


def install(runtime: Runtime) -> None:
    generate.register_fakes()


FEATURE = Feature("test_cases", routers=(router,), install=install, id_prefixes=frozenset({"tc"}))
