"""Dev-only usage seeder for quickstart section 6 (T081).

``uv run python -m app.usage.seed_demo --workspace ws_...`` charges one reference call and one
evaluation inside the default 30-day window and one evaluation 60 days ago (outside it).
Refuses to run with ENV=prod.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.billing import service
from app.core.config import get_settings
from app.core.db import Database
from app.core.ids import is_valid_id, new_id
from app.pricing import engine

REFERENCE = engine.Components(
    stt=engine.Selection("deepgram", "nova-3"),
    llm=engine.Selection("azure_openai", "gpt-5-mini"),
    tts=engine.Selection("elevenlabs", "eleven_flash_v2_5"),
)


async def seed(db: Database, workspace_id: str) -> None:
    now = datetime.now(UTC)
    async with db.transaction(workspace_id=workspace_id) as session:
        call_id = new_id("call")
        await service.charge_call(
            session,
            service.CallUsage(
                workspace_id=workspace_id,
                call_id=call_id,
                agent_version_id=None,
                started_at=now - timedelta(days=1),
                duration_ms=271_000,
                components=REFERENCE,
                meters={"llm_input_tokens": 102_348, "llm_output_tokens": 745, "tts_chars": 2_555},
            ),
        )
        for days_ago, key in ((2, "in-window"), (60, "outside-window")):
            await service.charge_feature(
                session,
                workspace_id=workspace_id,
                feature_key="eval.intent_fulfillment",
                quantity=Decimal(1),
                unit="runs",
                raw_cost_usd=Decimal("0.0002"),
                billable_cost_usd=Decimal("0.0004"),
                idempotency_key=f"seed-demo-{key}-{call_id}",
                ref_type="call",
                ref_id=call_id,
                occurred_at=now - timedelta(days=days_ago),
            )
    print(f"seeded {workspace_id}: call {call_id} ($0.477), one evaluation in window, one 60 days ago")


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.usage.seed_demo")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.dev_tools_enabled:
        print("seed_demo is disabled in production", file=sys.stderr)
        return 2
    if not is_valid_id(args.workspace, "ws"):
        print("--workspace must be a ws_ id", file=sys.stderr)
        return 2
    db = Database(settings.database_url, settings.database_admin_url, pool_size=1)
    try:
        await seed(db, args.workspace)
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
