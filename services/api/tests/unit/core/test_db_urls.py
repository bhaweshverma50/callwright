"""Database URLs for managed Postgres: transaction pooler detection, driver and SSL translation."""

from __future__ import annotations

import pytest

from app.core.db import async_engine_args, is_transaction_pooler, migration_url, sync_engine_url

POOLED = "postgresql://callwright_app.abcd:pw@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
SESSION = "postgresql://postgres.abcd:pw@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize(
    ("url", "pooled"),
    [
        (POOLED, True),
        (SESSION, False),
        ("postgresql+asyncpg://u:p@localhost:55432/db", False),
        ("postgresql+asyncpg://u:p@pgbouncer:6432/db?pgbouncer=true", True),
        ("postgresql+asyncpg://u:p@host:6543/db?pgbouncer=false", False),
    ],
)
def test_transaction_pooler_detection(url: str, pooled: bool) -> None:
    assert is_transaction_pooler(url) is pooled


def test_pooled_urls_disable_prepared_statement_caches() -> None:
    url, args = async_engine_args(POOLED + "?sslmode=require")
    assert url.drivername == "postgresql+asyncpg"
    assert dict(url.query) == {"ssl": "require"}
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    first, second = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
    assert first != second and first.startswith("__asyncpg_")


def test_direct_urls_keep_asyncpg_defaults() -> None:
    url, args = async_engine_args("postgres://u:p@db.abcd.supabase.co:5432/postgres?pgbouncer=false")
    assert url.drivername == "postgresql+asyncpg"
    assert "pgbouncer" not in url.query
    assert args == {}


def test_sync_url_uses_psycopg_and_sslmode() -> None:
    url = sync_engine_url("postgresql+asyncpg://u:p@h:5432/d?ssl=require&prepared_statement_cache_size=0")
    assert url.drivername == "postgresql+psycopg"
    assert dict(url.query) == {"sslmode": "require"}


def test_migrations_refuse_the_transaction_pooler() -> None:
    with pytest.raises(RuntimeError, match="session connection"):
        migration_url(POOLED)
    assert migration_url(SESSION).startswith("postgresql+psycopg://postgres.abcd:pw@")
