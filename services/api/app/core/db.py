"""Database engines and RLS-scoped transactions.

Every tenant query runs inside ``Database.transaction(workspace_id=..., user_id=...)``, which opens
one transaction and runs ``set_config('app.workspace_id', ..., true)`` (the function form of
``SET LOCAL``) before anything else, so the setting dies with the transaction and pooled
connections never leak a workspace id. Tenant tables carry RLS policies on that setting (R9).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


async def set_rls_context(session: AsyncSession, *, workspace_id: str | None, user_id: str | None) -> None:
    """Scope the current transaction to one workspace and user (empty means none)."""
    await session.execute(
        text("select set_config('app.workspace_id', :ws, true), set_config('app.user_id', :uid, true)"),
        {"ws": workspace_id or "", "uid": user_id or ""},
    )


class Database:
    def __init__(self, url: str, admin_url: str, *, pool_size: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True
        )
        self.admin_engine: AsyncEngine = create_async_engine(admin_url, pool_size=2, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._admin_sessions = async_sessionmaker(self.admin_engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(
        self, *, workspace_id: str | None = None, user_id: str | None = None
    ) -> AsyncIterator[AsyncSession]:
        """One transaction as the app role, scoped by RLS. Commits on success, rolls back on error."""
        async with self._sessions() as session, session.begin():
            await set_rls_context(session, workspace_id=workspace_id, user_id=user_id)
            yield session

    @asynccontextmanager
    async def admin_transaction(self) -> AsyncIterator[AsyncSession]:
        """One transaction as the admin role (global pricing writes, maintenance reads)."""
        async with self._admin_sessions() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
        await self.admin_engine.dispose()
