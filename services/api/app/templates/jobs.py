"""Template sync (T073, research R16): upsert ``seed/*.yaml`` into the global ``templates`` table
by slug and deactivate rows whose file was removed. Runs on deploy and in the test setup::

    uv run python -m app.templates.jobs sync

Writes go through the admin role (the app role can only read templates).
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from app.agent_versions.canonical import content_hash
from app.core.config import get_settings
from app.core.db import Database
from app.templates.models import Template

SEED_DIR = Path(__file__).with_name("seed")
FIELDS = ("category", "name", "description", "icon", "direction", "config", "sort_order")


@dataclass(frozen=True)
class SyncReport:
    inserted: int
    updated: int
    deactivated: int
    unchanged: int


def load_seed(seed_dir: Path = SEED_DIR) -> list[dict[str, Any]]:
    out = []
    for path in sorted(seed_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict) or "id" not in data:
            raise ValueError(f"{path.name}: a template file needs an id")
        out.append(data)
    ids = [t["id"] for t in out]
    if len(ids) != len(set(ids)):
        raise ValueError("template ids must be unique")
    return out


async def sync(db: Database, seed_dir: Path = SEED_DIR) -> SyncReport:
    seeds = {t["id"]: t for t in load_seed(seed_dir)}
    inserted = updated = deactivated = unchanged = 0
    async with db.admin_transaction() as session:
        existing = {t.id: t for t in (await session.execute(select(Template))).scalars()}
        for slug, seed in seeds.items():
            values = {name: seed[name] for name in FIELDS if name in seed}
            digest = content_hash(values)
            row = existing.get(slug)
            if row is None:
                session.add(Template(id=slug, is_active=True, content_hash=digest, **values))
                inserted += 1
            elif row.content_hash.strip() != digest or not row.is_active:
                for name, value in values.items():
                    setattr(row, name, value)
                row.content_hash = digest
                row.is_active = True
                updated += 1
            else:
                unchanged += 1
        for slug, row in existing.items():
            if slug not in seeds and row.is_active:
                row.is_active = False
                deactivated += 1
        await session.flush()
    return SyncReport(inserted, updated, deactivated, unchanged)


async def _main() -> int:
    settings = get_settings()
    db = Database(settings.database_url, settings.database_admin_url, pool_size=1)
    try:
        report = await sync(db)
    finally:
        await db.dispose()
    print(
        f"templates: {report.inserted} inserted, {report.updated} updated, "
        f"{report.deactivated} deactivated, {report.unchanged} unchanged"
    )
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["sync"]:
        print("usage: python -m app.templates.jobs sync", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(_main()))
