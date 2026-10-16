"""Grant the platform admin flag (``/v1/admin/*``) to a user by email.

``uv run python -m app.dev.make_admin ops@example.com`` (runs as the owner role,
DATABASE_OWNER_URL). There is no API for this on purpose.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def grant(email: str) -> bool:
    engine = create_async_engine(get_settings().database_owner_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("update users set is_admin = true where email = :e returning id"), {"e": email.lower()}
            )
            return result.first() is not None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m app.dev.make_admin <email>", file=sys.stderr)
        sys.exit(2)
    ok = asyncio.run(grant(sys.argv[1]))
    print("granted" if ok else "no such user")
    sys.exit(0 if ok else 1)
