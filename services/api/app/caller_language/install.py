"""Caller language (012): registers the claim's language options and start language with 003."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.caller_language.router import internal_router, router
from app.caller_language.service import start_language
from app.calls import ports
from app.core.feature import Feature, Runtime


class CallerLanguage:
    async def start(
        self, session: AsyncSession, call: Any, options: Sequence[Mapping[str, Any]]
    ) -> str | None:
        return await start_language(session, call, options)


def install(runtime: Runtime) -> None:
    ports.set_caller_language(CallerLanguage())


FEATURE = Feature(
    "caller_language",
    routers=(router, internal_router),
    install=install,
    id_prefixes=frozenset({"cpf", "clg"}),
)
