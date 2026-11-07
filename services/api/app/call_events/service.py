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
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from callwright_contract.adapters import AdapterCatalog
from callwright_contract.calls import ACCEPTS_EVENTS_STATUSES
from callwright_contract.protocol import Control, EventBatch, EventBatchResult, StatusEvent, UsageEvent
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.call_events.models import CallEvent
from app.calls import components as comp
from app.calls.effects import RUN_PIPELINE, Deferred
from app.calls.models import Call, billable_seconds, can_transition
from app.calls.ports import registry
from app.core.db import Database
from app.core.errors import ProblemError, not_found
from app.core.ids import is_valid_id
from app.pricing import engine
from app.pricing import service as pricing
from app.webhooks_out import service as webhooks

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


# Version config cache: versions are immutable, so a snapshot never changes.
_CONFIGS: OrderedDict[str, Mapping[str, Any]] = OrderedDict()
_CONFIG_CACHE_SIZE = 1024


async def version_config(session: AsyncSession, version_id: str | None) -> Mapping[str, Any] | None:
    if version_id is None:
        return None
    cached = _CONFIGS.get(version_id)
    if cached is not None:
        _CONFIGS.move_to_end(version_id)
        return cached
    snapshot = await registry.agent_versions.get_snapshot(session, version_id)
    if snapshot is None:
        return None
    _CONFIGS[version_id] = snapshot.config
    if len(_CONFIGS) > _CONFIG_CACHE_SIZE:
        _CONFIGS.popitem(last=False)
    return snapshot.config


async def running_cost(
    session: AsyncSession, call: Call, catalog: AdapterCatalog, now: datetime
) -> Decimal | None:
    """Cost so far: 001 pricing over the latest meters and the connected time until ``now``."""
    if call.connected_at is None:
        return None
    config = await version_config(session, call.agent_version_id)
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
    session: AsyncSession,
    call: Call,
    event: StatusEvent,
    config: Mapping[str, Any] | None,
    deferred: Deferred,
    now: datetime,
) -> None:
    new = event.status
    at = event.occurred_at
    current = call.status
    if new == "ended" and current in ("queued", "ringing"):
        # Ended before connecting: a never-connected outcome, not billed (FR-035).
        new = "failed"
    if not can_transition(current, new):
        logger.info("stale status %s -> %s ignored for %s", current, new, call.id)
        return
    call.status = new
    if new == "ringing":
        call.ringing_at = at
    elif new == "in_progress":
        call.connected_at = at
        await session.flush()
        await webhooks.enqueue_event(session, call, "call_started", config=config, deferred=deferred, now=now)
    elif new == "ended":
        assert call.connected_at is not None
        call.ended_at = max(at, call.connected_at)
        call.disconnect_reason = event.disconnect_reason or "error"
        call.diagnostic = event.diagnostic
        call.billable_seconds = billable_seconds(call.connected_at, call.ended_at)
        await session.flush()
        await webhooks.enqueue_event(session, call, "call_ended", config=config, deferred=deferred, now=now)
        deferred.add(RUN_PIPELINE, call.workspace_id, call.id)
    else:  # failed, no_answer, busy: never connected
        call.ended_at = at
        call.billable_seconds = 0
        call.diagnostic = event.diagnostic
        if new == "failed":
            call.disconnect_reason = event.disconnect_reason or "error"
        await session.flush()
        await webhooks.enqueue_event(session, call, "call_ended", config=config, deferred=deferred, now=now)


async def workspace_for_call(db: Database, call_id: str) -> str:
    if not is_valid_id(call_id, "call"):
        raise not_found("call")
    async with db.transaction() as session:
        workspace_id = (
            await session.execute(text("select calls_workspace_for(:id)"), {"id": call_id})
        ).scalar()
    if workspace_id is None:
        raise not_found("call")
    return str(workspace_id)


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
        config = await version_config(session, call.agent_version_id)
        for event in sorted(
            (e for e in events if isinstance(e, StatusEvent) and e.seq in inserted), key=lambda e: e.seq
        ):
            await _apply_status(session, call, event, config, out.deferred, now)
        call.last_heartbeat_at = now
        await session.flush()
        # Simulations are billed as feature charges (008), never as call minutes.
        if call.status == "in_progress" and call.origin != "simulation":
            cost = await running_cost(session, call, catalog, now)
            if cost is not None:
                balance = await billing.get_balance(session, workspace_id)
                out.result.control = credit_control(balance, cost, grace_usd)
                if out.result.control.action == "end_call":
                    logger.info("call %s over credit: balance %s, running cost %s", call_id, balance, cost)
    return out
