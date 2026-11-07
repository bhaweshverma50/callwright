"""Datasets (008 T079; FR-025 to FR-029, US5).

A dataset is a named list of completed live calls of one agent; names are unique per
workspace ignoring case. Adding checks each call in the data-model order (not found, wrong
agent, simulated, not completed, transcript purged) and counts calls already present as
duplicates; a dataset holds at most 1,000 calls. Calls purged by retention read as unavailable
and are skipped by bulk actions. Bulk evaluate queues 007's evaluators on every available call
(``trigger = dataset``), optionally only where current results are missing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.calls import transcript
from app.calls.models import Call
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.datasets.models import Dataset, DatasetItem
from app.evaluators.settings import judge_models
from app.testing import calls as sim_calls
from app.testing.targets import require_agent

MAX_ITEMS = 1000


def name_taken() -> ProblemError:
    return ProblemError(
        409,
        "name_taken",
        "Name already in use",
        "A dataset with this name already exists. Choose another name.",
        errors=[field_error("/name", "taken", "Name already in use")],
    )


def dataset_view(d: Dataset, agent_name: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dataset_id": d.id,
        "name": d.name,
        "description": d.description,
        "agent_id": d.agent_id,
        "item_count": d.item_count,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }
    if agent_name is not None:
        out["agent_name"] = agent_name
    return out


async def agent_name(session: AsyncSession, agent_id: str) -> str | None:
    agent = await session.get(Agent, agent_id)
    return agent.name if agent is not None else None


async def _name_used(session: AsyncSession, name: str, exclude: str | None = None) -> bool:
    query = select(Dataset.id).where(func.lower(Dataset.name) == name.casefold())
    if exclude:
        query = query.where(Dataset.id != exclude)
    return (await session.execute(query)).first() is not None


async def get_dataset(session: AsyncSession, dataset_id: str, *, lock: bool = False) -> Dataset:
    if not is_valid_id(dataset_id, "ds"):
        raise not_found("dataset")
    query = select(Dataset).where(Dataset.id == dataset_id)
    if lock:
        query = query.with_for_update()
    dataset = (await session.execute(query)).scalar_one_or_none()
    if dataset is None:
        raise not_found("dataset")
    return dataset


async def create_dataset(
    session: AsyncSession, workspace_id: str, *, name: str, description: str | None, agent_id: str
) -> Dataset:
    name = name.strip()
    errors = []
    if not name:
        errors.append(field_error("/name", "required", "Enter a name"))
    if errors:
        raise validation_failed(errors)
    await require_agent(session, agent_id, pointer="/agent_id")
    if await _name_used(session, name):
        raise name_taken()
    now = datetime.now(UTC)
    dataset = Dataset(
        id=new_id("ds"),
        workspace_id=workspace_id,
        agent_id=agent_id,
        name=name,
        description=(description or "").strip() or None,
        item_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(dataset)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise name_taken() from exc
    return dataset


async def update_dataset(session: AsyncSession, dataset_id: str, changes: Mapping[str, Any]) -> Dataset:
    dataset = await get_dataset(session, dataset_id, lock=True)
    if "name" in changes:
        name = str(changes["name"] or "").strip()
        if not name:
            raise validation_failed([field_error("/name", "required", "Enter a name")])
        if await _name_used(session, name, exclude=dataset.id):
            raise name_taken()
        dataset.name = name
    if "description" in changes:
        dataset.description = (changes["description"] or "").strip() or None
    dataset.updated_at = datetime.now(UTC)
    await session.flush()
    return dataset


async def delete_dataset(session: AsyncSession, dataset_id: str) -> None:
    dataset = await get_dataset(session, dataset_id)
    await session.delete(dataset)


def classify(
    call_ids: Sequence[str], calls: Mapping[str, Call], agent_id: str, present: set[str]
) -> tuple[list[str], int, list[dict[str, str]]]:
    """(calls to add, duplicates, invalid with reasons), each call once in request order."""
    added: list[str] = []
    duplicates = 0
    invalid: list[dict[str, str]] = []
    seen: set[str] = set()
    for call_id in call_ids:
        if call_id in seen:
            duplicates += 1
            continue
        seen.add(call_id)
        reason = sim_calls.call_problem(calls.get(call_id), agent_id)
        if reason:
            invalid.append({"call_id": call_id, "reason": reason})
        elif call_id in present:
            duplicates += 1
        else:
            added.append(call_id)
    return added, duplicates, invalid


def check_capacity(current: int, adding: int) -> None:
    if current + adding > MAX_ITEMS:
        raise ProblemError(
            422,
            "dataset_full",
            "Dataset full",
            f"A dataset holds at most {MAX_ITEMS} calls; this one has {current} and {adding} would be added.",
        )


async def add_items(session: AsyncSession, dataset_id: str, call_ids: Sequence[str]) -> dict[str, Any]:
    dataset = await get_dataset(session, dataset_id, lock=True)
    calls = await sim_calls.load_calls(session, call_ids)
    present = set(
        (
            await session.execute(
                select(DatasetItem.call_id).where(
                    DatasetItem.dataset_id == dataset.id, DatasetItem.call_id.in_(list(calls))
                )
            )
        ).scalars()
    )
    added, duplicates, invalid = classify(call_ids, calls, dataset.agent_id, present)
    check_capacity(dataset.item_count, len(added))
    now = datetime.now(UTC)
    for call_id in added:
        session.add(
            DatasetItem(
                dataset_id=dataset.id, call_id=call_id, workspace_id=dataset.workspace_id, added_at=now
            )
        )
    dataset.item_count += len(added)
    dataset.updated_at = now
    await session.flush()
    return {
        "added": len(added),
        "skipped_duplicates": duplicates,
        "skipped_invalid": len(invalid),
        "invalid": invalid,
    }


async def remove_item(session: AsyncSession, dataset_id: str, call_id: str) -> None:
    dataset = await get_dataset(session, dataset_id, lock=True)
    result = await session.execute(
        delete(DatasetItem).where(DatasetItem.dataset_id == dataset.id, DatasetItem.call_id == call_id)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise not_found("dataset item")
    dataset.item_count = max(0, dataset.item_count - 1)
    dataset.updated_at = datetime.now(UTC)


async def list_datasets(
    session: AsyncSession, *, agent_id: str | None, page: int, page_size: int
) -> tuple[list[tuple[Dataset, str | None]], int]:
    where = [Dataset.agent_id == agent_id] if agent_id else []
    total = int((await session.execute(select(func.count()).select_from(Dataset).where(*where))).scalar_one())
    rows = await session.execute(
        select(Dataset, Agent.name)
        .join(Agent, Agent.id == Dataset.agent_id, isouter=True)
        .where(*where)
        .order_by(Dataset.updated_at.desc(), Dataset.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [(d, n) for d, n in rows.all()], total


async def list_items(
    session: AsyncSession, dataset_id: str, *, page: int, page_size: int
) -> tuple[list[dict[str, Any]], int]:
    dataset = await get_dataset(session, dataset_id)
    total = dataset.item_count
    rows = (
        await session.execute(
            text(
                "select i.call_id, i.added_at, c.status, c.connected_at, c.created_at, c.billable_seconds, "
                "c.sentiment, c.transcript "
                "from dataset_items i join calls c on c.id = i.call_id "
                "where i.dataset_id = :ds order by i.added_at desc, i.call_id offset :off limit :lim"
            ),
            {"ds": dataset.id, "off": (page - 1) * page_size, "lim": page_size},
        )
    ).all()
    statuses = await eval_statuses(session, [r.call_id for r in rows])
    items = []
    for r in rows:
        started = r.connected_at or r.created_at
        sentiment = r.sentiment if r.sentiment in ("positive", "neutral", "negative") else None
        items.append(
            {
                "call_id": r.call_id,
                "added_at": r.added_at.isoformat(),
                "available": transcript.has_conversation(r.transcript),
                "started_at": started.isoformat() if started else None,
                "duration_s": r.billable_seconds,
                "call_status": r.status,
                "eval_status": statuses.get(r.call_id),
                "sentiment": sentiment,
            }
        )
    return items, total


async def eval_statuses(session: AsyncSession, call_ids: Sequence[str]) -> dict[str, str]:
    from app.evals.models import EvaluatorRun
    from app.evals.views import split_current, status_of

    if not call_ids:
        return {}
    runs: dict[str, list[EvaluatorRun]] = {}
    for row in (
        await session.execute(select(EvaluatorRun).where(EvaluatorRun.call_id.in_(list(call_ids))))
    ).scalars():
        runs.setdefault(row.call_id, []).append(row)
    out: dict[str, str] = {}
    for call_id in call_ids:
        current, _ = split_current(runs.get(call_id, []))
        out[call_id] = status_of(current)[0]
    return out


async def evaluate(
    session: AsyncSession, dataset_id: str, *, only_missing: bool, idempotency_key: str, user_id: str | None
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Start a ``dataset`` run group on every available call. Returns the counts and the
    (call id, run group id) pairs to execute after commit."""
    from app.evals.jobs import start_evaluation
    from app.evals.models import EvaluatorRun
    from app.evals.runner import AlreadyRunning
    from app.evals.service import resolve_all
    from app.evals.views import split_current
    from app.llms.runtime import runtime

    dataset = await get_dataset(session, dataset_id)
    agent = await session.get(Agent, dataset.agent_id)
    ids = list(
        (
            await session.execute(select(DatasetItem.call_id).where(DatasetItem.dataset_id == dataset.id))
        ).scalars()
    )
    calls = await sim_calls.load_calls(session, ids)
    enabled: dict[str, int] = {}
    if agent is not None:
        enabled = {
            r.row.id: r.row.current_version
            for r in await resolve_all(session, agent, judge_models(runtime().settings))
            if r.enabled
        }
    runs: dict[str, list[EvaluatorRun]] = {}
    if only_missing and ids:
        for row in (
            await session.execute(select(EvaluatorRun).where(EvaluatorRun.call_id.in_(ids)))
        ).scalars():
            runs.setdefault(row.call_id, []).append(row)
    counts = {"enqueued": 0, "skipped_up_to_date": 0, "skipped_unavailable": 0}
    jobs: list[tuple[str, str]] = []
    for call_id in ids:
        call = calls.get(call_id)
        if call is None or not transcript.has_conversation(call.transcript):
            counts["skipped_unavailable"] += 1
            continue
        if only_missing:
            current, _ = split_current(runs.get(call_id, []))
            have = {r.evaluator_id: r.evaluator_version for r in current if r.status == "completed"}
            if all(have.get(e) == v for e, v in enabled.items()):
                counts["skipped_up_to_date"] += 1
                continue
        try:
            start = await start_evaluation(
                session,
                call,
                trigger="dataset",
                idempotency_key=f"ds:{dataset.id}:{idempotency_key}",
                user_id=user_id,
            )
        except AlreadyRunning:
            counts["enqueued"] += 1  # checks already running for this call
            continue
        counts["enqueued"] += 1
        if start.created and start.group.status == "active":
            jobs.append((call_id, start.group.run_group_id))
    return counts, jobs
