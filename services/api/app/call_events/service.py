"""Event ingest: storage, status transitions, usage snapshots, heartbeat and the mid-call credit
guard (003 T033, T053, T080, T093; research R3, R7).

Every post is a heartbeat (``calls.last_heartbeat_at``). Events are stored with
``ON CONFLICT (call_id, seq) DO NOTHING``; only newly stored status events move the call, so a
retried batch changes nothing. The usage snapshot with the highest ``seq`` wins and a lower
``seq`` than the stored one is ignored, so cumulative counters never go backwards. While the
call is connected the running cost (001 pricing on the latest meters and elapsed connected time)
is compared with the balance: below ``-CREDIT_GRACE_USD`` the response orders ``end_call`` with
``insufficient_credit`` (FR-025).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from callwright_contract.adapters import AdapterCatalog
from callwright_contract.calls import ACCEPTS_EVENTS_STATUSES
from callwright_contract.protocol import Control, EventBatch, EventBatchResult, StatusEvent, UsageEvent
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.calls import components as comp
from app.calls import lifecycle
from app.calls.lookups import config_for, workspace_for_call
from app.calls.models import Call, CallEvent
from app.calls.origins import policy
from app.core.db import Database
from app.core.errors import ProblemError
from app.core.queue import Deferred
from app.pricing import engine
from app.pricing import service as pricing

logger = logging.getLogger(__name__)

_BASE_FIELDS = {"seq", "type", "occurred_at", "offset_ms"}
_TURN_COLUMNS = (
    "turn_index",
    "stt_final_ms",
    "eou_delay_ms",
    "llm_ttft_ms",
    "tts_ttfb_ms",
    "e2e_ms",
    "tool_ms",
)


# Pure rules (money tests T025, T047) --------------------------------------------------------


def latest_usage(stored_seq: int, events: Sequence[Any]) -> tuple[int, dict[str, Any]] | None:
    """The usage snapshot to store: highest ``seq`` above ``stored_seq``, else None."""
    best: UsageEvent | None = None
    for event in events:
        if (
            isinstance(event, UsageEvent)
            and event.seq > stored_seq
            and (best is None or event.seq > best.seq)
        ):
            best = event
    if best is None:
        return None
    return best.seq, best.usage.model_dump(mode="json")


def credit_control(balance_usd: Decimal, running_cost_usd: Decimal, grace_usd: Decimal) -> Control:
    """``end_call`` once the balance minus the running cost falls below minus the grace."""
    if balance_usd - running_cost_usd < -grace_usd:
        return Control(action="end_call", disconnect_reason="insufficient_credit")
    return Control(action="none")


async def running_cost(
    session: AsyncSession, call: Call, catalog: AdapterCatalog, now: datetime
) -> Decimal | None:
    """Cost so far: 001 pricing over the latest meters and the connected time until ``now``."""
    if call.connected_at is None:
        return None
    config = await config_for(session, call)
    if config is None:
        return None
    components = comp.resolve(config, catalog).pricing(call.usage)
    meters = comp.usage_meters(call.usage)
    duration_ms = max(0, int((now - call.connected_at).total_seconds() * 1000))
    usage = engine.Usage(
        duration_ms=duration_ms,
        llm_input_tokens=meters["llm_input_tokens"],
        llm_output_tokens=meters["llm_output_tokens"],
        tts_chars=meters["tts_chars"],
    )
    try:
        quote = await pricing.quote(session, components, usage, at=call.connected_at)
    except pricing.CatalogUnavailable:
        return None
    if quote.call is None or not quote.call.complete:
        return None
    return quote.call.total_usd


# Ingest ---------------------------------------------------------------------------------------


@dataclass
class IngestResult:
    result: EventBatchResult
    deferred: Deferred = field(default_factory=Deferred)


def _row(call: Call, event: Any) -> dict[str, Any]:
    data = event.model_dump(mode="json", exclude_unset=True)
    row: dict[str, Any] = {
        "workspace_id": call.workspace_id,
        "call_id": call.id,
        "seq": event.seq,
        "type": event.type,
        "occurred_at": event.occurred_at,
        "offset_ms": event.offset_ms,
        "payload": {k: v for k, v in data.items() if k not in _BASE_FIELDS},
    }
    # Every row carries every column: a multi-row INSERT takes its column list from the first row.
    turn = event.type == "turn"
    for column in _TURN_COLUMNS:
        row[column] = data.get(column) if turn else None
    row["interrupted"] = data.get("interrupted") if turn else None
    return row


async def _apply_status(
    session: AsyncSession, call: Call, event: StatusEvent, deferred: Deferred, now: datetime
) -> None:
    at = event.occurred_at
    if event.status == "ringing":
        await lifecycle.ring(session, call, at)
    elif event.status == "in_progress":
        await lifecycle.connect(session, call, at, deferred=deferred, now=now)
    elif event.status == "ended" and call.status not in ("queued", "ringing"):
        await lifecycle.end_connected(
            session,
            call,
            at=at,
            reason=event.disconnect_reason or "error",
            diagnostic=event.diagnostic,
            deferred=deferred,
            now=now,
        )
    else:
        # Ended before connecting is a never-connected outcome, not billed (FR-035).
        await lifecycle.fail_unconnected(
            session,
            call,
            status="failed" if event.status == "ended" else event.status,
            at=at,
            reason=event.disconnect_reason,
            diagnostic=event.diagnostic,
            deferred=deferred,
            now=now,
        )


def call_closed() -> ProblemError:
    return ProblemError(409, "call_closed", "Call is closed", "The call has ended; stop posting events.")


async def ingest(
    db: Database,
    call_id: str,
    batch: EventBatch,
    *,
    catalog: AdapterCatalog,
    grace_usd: Decimal,
    now: datetime | None = None,
) -> IngestResult:
    now = now or datetime.now(UTC)
    workspace_id = await workspace_for_call(db, call_id)
    out = IngestResult(EventBatchResult(accepted=0, duplicates=0, control=Control()))
    async with db.transaction(workspace_id=workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id).with_for_update())).scalar_one()
        if call.status not in ACCEPTS_EVENTS_STATUSES:
            raise call_closed()
        events = list(batch.events)
        inserted: set[int] = set()
        if events:
            stmt = (
                insert(CallEvent)
                .values([_row(call, e) for e in events])
                .on_conflict_do_nothing(index_elements=["call_id", "seq"])
                .returning(CallEvent.seq)
            )
            inserted = {int(seq) for seq in (await session.execute(stmt)).scalars()}
        unique_seqs = {e.seq for e in events}
        out.result.accepted = len(inserted)
        out.result.duplicates = len(events) - len(inserted)
        if len(unique_seqs) < len(events):
            logger.warning("batch for %s repeats seq values", call_id)
        snapshot = latest_usage(call.usage_seq, events)
        if snapshot is not None:
            call.usage_seq, call.usage = snapshot
        for event in sorted(
            (e for e in events if isinstance(e, StatusEvent) and e.seq in inserted), key=lambda e: e.seq
        ):
            await _apply_status(session, call, event, out.deferred, now)
        call.last_heartbeat_at = now
        await session.flush()
        if call.status == "in_progress" and policy(call.origin).billable:
            cost = await running_cost(session, call, catalog, now)
            if cost is not None:
                balance = await billing.get_balance(session, workspace_id)
                out.result.control = credit_control(balance, cost, grace_usd)
                if out.result.control.action == "end_call":
                    logger.info("call %s over credit: balance %s, running cost %s", call_id, balance, cost)
    return out
