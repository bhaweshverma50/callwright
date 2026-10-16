"""Alembic environment. Migrations run as the database owner (DATABASE_OWNER_URL).

The owner role must be able to create roles and needs BYPASSRLS (or superuser), because the
security-definer lookup functions read across workspaces. Migrations use the synchronous
psycopg driver so a migration may run multi-statement SQL scripts.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.core.db import migration_url

config = context.config


def sync_url(url: str) -> str:
    return migration_url(url)


def _url() -> str:
    return sync_url(
        os.environ.get("ALEMBIC_DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or get_settings().database_owner_url
    )


if context.is_offline_mode():
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
