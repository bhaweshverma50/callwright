"""Shared fixtures.

Database tests run against ``callwright_test`` on the compose Postgres (host port 55432) and Redis
database 15 (port 56379). The session fixture drops and recreates the schema and runs every
Alembic migration, so each run starts clean. Override with ``TEST_PG`` (``host:port``) and
``TEST_REDIS_URL``. Nothing here touches the network beyond those two local services.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.core.config import Settings
from app.core.db import Database
from app.main import create_app

pytest_plugins = ("tests.runtime_support", "tests.quality_support")

API_DIR = Path(__file__).resolve().parents[1]
PG = os.environ.get("TEST_PG", "localhost:55432")
TEST_DB = os.environ.get("TEST_DB_NAME", "callwright_test")
OWNER_URL = f"postgresql+asyncpg://callwright:callwright@{PG}/{TEST_DB}"
APP_URL = f"postgresql+asyncpg://callwright_app:callwright_app@{PG}/{TEST_DB}"
ADMIN_URL = f"postgresql+asyncpg://callwright_admin:callwright_admin@{PG}/{TEST_DB}"
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/15")
PASSWORD = "correct-horse-9"
DEFAULT_IP = "10.0.0.1"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "database_url": APP_URL,
        "database_admin_url": ADMIN_URL,
        "database_owner_url": OWNER_URL,
        "redis_url": REDIS_URL,
        "auth_provider": "local",
        "stripe_mode": "fake",
        "auth_email_rate_limit_per_hour": 100_000,
        "log_level": "WARNING",
        "db_pool_size": 5,
        "livekit_mode": "fake",
        "livekit_api_secret": "test-livekit-secret-0123456789abcdef",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _sync_dsn(db: str) -> str:
    return f"postgresql://callwright:callwright@{PG}/{db}"


def _reset_database() -> None:
    with psycopg.connect(_sync_dsn("postgres"), autocommit=True) as conn:
        exists = conn.execute("select 1 from pg_database where datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute(f'create database "{TEST_DB}" owner callwright')
    with psycopg.connect(_sync_dsn(TEST_DB), autocommit=True) as conn:
        conn.execute("drop schema if exists local_idp cascade")
        conn.execute("drop schema if exists public cascade")
        conn.execute("create schema public")
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "app" / "migrations"))
    os.environ["ALEMBIC_DATABASE_URL"] = OWNER_URL
    try:
        command.upgrade(cfg, "head")
    finally:
        os.environ.pop("ALEMBIC_DATABASE_URL", None)


@pytest.fixture(scope="session")
def migrated() -> Iterator[None]:
    _reset_database()
    yield


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_settings()


@pytest_asyncio.fixture(scope="session")
async def app(migrated: None, settings: Settings) -> AsyncIterator[FastAPI]:
    from app.agents import checks
    from app.templates.jobs import sync as sync_templates

    async def no_dns(host: str) -> list[str]:
        # Webhook hosts resolve to a public address in tests; no network lookups.
        return ["93.184.216.34"] if host != "private.test.example" else ["10.0.0.5"]

    checks.webhook_resolver = no_dns
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        await application.state.redis.flushdb()
        await sync_templates(application.state.db)
        yield application


@pytest.fixture
def db(app: FastAPI) -> Database:
    database: Database = app.state.db
    return database


def make_client(app: FastAPI, ip: str = DEFAULT_IP) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as c:
        yield c


def unique_email(tag: str = "user") -> str:
    return f"{tag}+{uuid.uuid4().hex[:12]}@example.com"


@dataclass
class Account:
    email: str
    password: str
    access_token: str
    refresh_token: str
    user_id: str
    workspace_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def latest_token(app: FastAPI, email: str, kind: str) -> str:
    message = app.state.idp.latest_message(email, kind)
    assert message is not None, f"no {kind} mail for {email}"
    token: str = message.token_hash
    return token


async def register(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> None:
    response = await client.post("/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 202, response.text


async def signup(
    client: httpx.AsyncClient, app: FastAPI, email: str | None = None, password: str = PASSWORD
) -> Account:
    """Register, verify through the dev outbox and read /v1/me."""
    email = email or unique_email()
    await register(client, email, password)
    verified = await client.post(
        "/v1/auth/verify-email", json={"token_hash": latest_token(app, email, "verify_email")}
    )
    assert verified.status_code == 200, verified.text
    tokens = verified.json()
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200, me.text
    body = me.json()
    return Account(
        email=email,
        password=password,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        user_id=body["user"]["id"],
        workspace_id=body["workspace"]["id"],
    )


@pytest_asyncio.fixture
async def account(client: httpx.AsyncClient, app: FastAPI) -> Account:
    return await signup(client, app)


async def make_workspace(app: FastAPI, *, trial: bool = True) -> tuple[str, str]:
    """A verified user and workspace created directly (no HTTP). Returns (user_id, workspace_id)."""
    from app.workspaces.service import bootstrap_workspace

    settings: Settings = app.state.settings
    if not trial:
        settings = settings.model_copy(update={"trial_credit_usd": 0})
    result = await bootstrap_workspace(
        app.state.db, settings, subject=str(uuid.uuid4()), email=unique_email("direct")
    )
    return result.user_id, result.workspace_id


async def make_admin(account: Account) -> None:
    with psycopg.connect(_sync_dsn(TEST_DB), autocommit=True) as conn:
        conn.execute("update users set is_admin = true where id = %s", (account.user_id,))


FUTURE_V2_FROM = "2099-01-01T00:00:00+00:00"


@pytest_asyncio.fixture(scope="session")
async def future_catalog(app: FastAPI) -> int:
    """Publish a catalog version effective in 2099 with the STT rates doubled (version pinning
    tests). Far in the future so every other test keeps pricing with version 1."""
    from datetime import datetime

    from app.pricing import service

    async with app.state.db.transaction() as session:
        v1 = await service.catalog_version(session, 1)
    entries = [
        service.EntryInput(
            r.component,
            r.provider,
            r.model,
            r.label,
            r.rate_per_min_usd * (2 if r.component == "stt" else 1),
            r.bundles,
        )
        for r in v1.call_rates()
    ]
    async with app.state.db.admin_transaction() as admin:
        catalog = await service.publish_version(
            admin,
            effective_from=datetime.fromisoformat(FUTURE_V2_FROM),
            entries=entries,
            notes="test: STT doubled",
            published_by=None,
        )
    assert catalog.version >= 2
    return catalog.version
