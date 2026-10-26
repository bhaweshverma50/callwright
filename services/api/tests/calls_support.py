"""006 test support: one seeded call history shared by the calls, recordings and dashboard tests.

``seeded_calls`` signs up two workspaces (A and B) and seeds A with ``app.dev.seed_calls``
(45 calls plus 2 simulation calls, the 001 reference call among them). B stays empty, so any row
it can read is a tenancy leak.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import psycopg
import pytest_asyncio
from fastapi import FastAPI

from app.dev.seed_calls import SeedResult, seed
from tests.conftest import Account, make_client, signup
from tests.runtime_support import _owner_dsn


@dataclass
class SeededCalls:
    a: Account
    b: Account
    data: SeedResult


@pytest_asyncio.fixture(scope="session")
async def seeded_calls(app: FastAPI) -> AsyncIterator[SeededCalls]:
    async with make_client(app, ip="10.6.0.1") as client:
        a = await signup(client, app)
        b = await signup(client, app)
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        data = seed(conn, a.workspace_id)
    yield SeededCalls(a, b, data)
