"""Database engines and RLS-scoped transactions.

Every tenant query runs inside ``Database.transaction(workspace_id=..., user_id=...)``, which opens
one transaction and runs ``set_config('app.workspace_id', ..., true)`` (the function form of
``SET LOCAL``) before anything else, so the setting dies with the transaction and pooled
connections never leak a workspace id. Tenant tables carry RLS policies on that setting (R9).

Managed Postgres (Supabase): the app and admin URLs may point at a transaction-mode pooler
(Supavisor or PgBouncer, port 6543, or any URL with ``?pgbouncer=true``). Such a pooler hands each
transaction to any server connection, so prepared statements cannot be reused: the asyncpg
statement caches are switched off and statement names are made unique. Transaction-local
``set_config`` is safe there. Migrations need a session connection (direct, or the session
pooler on port 5432). ``postgres://``/``postgresql://`` URLs as copied from a dashboard are
accepted and given the right driver; ``sslmode`` and ``ssl`` are translated between drivers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import MetaData, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

TRANSACTION_POOLER_PORT = 6543
_TRUE = {"1", "true", "yes", "on"}
# Query parameters that only mean something to our engine setup or to asyncpg.
_ASYNC_ONLY = ("pgbouncer", "prepared_statement_cache_size", "statement_cache_size")


def escape_like(text: str) -> str:
    """``text`` as a literal inside a LIKE pattern (backslash is the default escape character)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _with_driver(raw: str, driver: str) -> URL:
    url = make_url(raw)
    if url.drivername in ("postgres", "postgresql") or url.drivername.startswith("postgresql+"):
        url = url.set(drivername=f"postgresql+{driver}")
    return url


def is_transaction_pooler(raw: str | URL) -> bool:
    """True for a transaction-mode pooler: ``?pgbouncer=true|false`` decides, else port 6543."""
    url = make_url(raw) if isinstance(raw, str) else raw
    flag = url.query.get("pgbouncer")
    if flag is not None:
        return str(flag).lower() in _TRUE
    return url.port == TRANSACTION_POOLER_PORT


def async_engine_args(raw: str) -> tuple[URL, dict[str, Any]]:
    """The asyncpg URL and ``connect_args`` for an app or admin engine."""
    url = _with_driver(raw, "asyncpg")
    pooled = is_transaction_pooler(url)
    query = dict(url.query)
    if "sslmode" in query and "ssl" not in query:
        query["ssl"] = query["sslmode"]
    query.pop("sslmode", None)
    query.pop("pgbouncer", None)
    url = url.set(query=query)
    connect_args: dict[str, Any] = {}
    if pooled:
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
        }
    return url, connect_args


def sync_engine_url(raw: str) -> URL:
    """The psycopg URL for Alembic (and other synchronous tools) from any configured URL."""
    url = _with_driver(raw, "psycopg")
    query = {k: v for k, v in url.query.items() if k not in _ASYNC_ONLY}
    if "ssl" in query and "sslmode" not in query:
        query["sslmode"] = query["ssl"]
    query.pop("ssl", None)
    return url.set(query=query)


def migration_url(raw: str) -> str:
    """The psycopg URL Alembic connects with. Refuses a transaction pooler: migrations run DDL
    and multi-statement scripts that need a session (direct connection or session pooler)."""
    if is_transaction_pooler(raw):
        raise RuntimeError(
            "migrations need a session connection: point DATABASE_OWNER_URL (or ALEMBIC_DATABASE_URL) "
            "at the direct database or the session pooler on port 5432, not the transaction pooler"
        )
    return sync_engine_url(raw).render_as_string(hide_password=False)


def make_engine(raw: str, **kwargs: Any) -> AsyncEngine:
    url, connect_args = async_engine_args(raw)
    return create_async_engine(url, connect_args=connect_args, **kwargs)


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
        self.engine: AsyncEngine = make_engine(
            url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True
        )
        self.admin_engine: AsyncEngine = make_engine(admin_url, pool_size=2, pool_pre_ping=True)
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
