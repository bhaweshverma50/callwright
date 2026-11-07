"""Evaluator catalog reads and custom evaluator CRUD, versioning, soft delete and trial
(007 T034, T060, T087; FR-009 to FR-012, FR-044).

* A custom check's machine name is derived from its display name when omitted (lowercase,
  everything else to underscores, leading digits and underscores dropped); uniqueness applies to
  that name among the workspace's live custom checks and the built-in names.
* A change to ``config`` creates a new immutable version; display name and description edits do
  not. Deleting hides the check from catalogs and frees its name; versions and runs are kept.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, field_error, forbidden, not_found, validation_failed
from app.core.ids import new_id
from app.evaluators.models import EvaluatorRow, EvaluatorVersion
from app.evaluators.registry import BUILTINS, CUSTOM_TYPES
from app.evaluators.settings import served_schema

MAX_CUSTOM = 50
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def derive_name(display_name: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", display_name.lower())
    name = re.sub(r"_+", "_", name)
    name = re.sub(r"^[0-9_]+", "", name).strip("_")
    return name[:64].rstrip("_")


def evaluator_view(
    row: EvaluatorRow, judge_models: Sequence[str], config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "evaluator_type": row.evaluator_type,
        "name": row.name,
        "display_name": row.display_name,
        "description": row.description,
        "scope": row.scope,
        "cost_class": row.cost_class,
        "output_kind": row.output_kind,
        "agent_types": list(row.agent_types),
        "settings_schema": served_schema(row.settings_schema or {"fields": []}, judge_models),
        "score_range": row.score_range or {"min": 0, "max": 1},
        "current_version": row.current_version,
        "enabled_by_default": row.enabled_by_default,
        "config": dict(config) if config is not None and row.kind == "custom" else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def version_view(v: EvaluatorVersion) -> dict[str, Any]:
    return {
        "version": v.version,
        "judge_model": v.judge_model,
        "definition": dict(v.definition or {}),
        "created_at": v.created_at.isoformat(),
    }


async def list_evaluators(
    session: AsyncSession,
    *,
    kind: str | None = None,
    agent_type: str | None = None,
    include_deleted: bool = False,
) -> list[EvaluatorRow]:
    query = select(EvaluatorRow)
    if kind:
        query = query.where(EvaluatorRow.kind == kind)
    if agent_type:
        query = query.where(EvaluatorRow.agent_types.contains([agent_type]))
    if not include_deleted:
        query = query.where(EvaluatorRow.deleted_at.is_(None))
    rows = list((await session.execute(query)).scalars())
    return sorted(rows, key=lambda r: (r.display_name.casefold(), r.name))


async def current_definitions(
    session: AsyncSession, rows: Sequence[EvaluatorRow]
) -> dict[str, dict[str, Any]]:
    if not rows:
        return {}
    pairs = [(r.id, r.current_version) for r in rows]
    found = await session.execute(
        select(EvaluatorVersion).where(
            or_(*[(EvaluatorVersion.evaluator_id == i) & (EvaluatorVersion.version == v) for i, v in pairs])
        )
    )
    return {v.evaluator_id: dict(v.definition or {}) for v in found.scalars()}


async def get_evaluator(session: AsyncSession, evaluator_id: str) -> EvaluatorRow:
    row = await session.get(EvaluatorRow, evaluator_id)
    if row is None:
        raise not_found("evaluator")
    return row


async def versions_of(session: AsyncSession, evaluator_id: str) -> list[EvaluatorVersion]:
    rows = await session.execute(
        select(EvaluatorVersion)
        .where(EvaluatorVersion.evaluator_id == evaluator_id)
        .order_by(EvaluatorVersion.version)
    )
    return list(rows.scalars())


def validate_config(
    evaluator_type: Any, config: Any, judge_models: Sequence[str]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Normalised config and field errors (pointers under ``/config``)."""
    if evaluator_type not in CUSTOM_TYPES:
        return {}, [
            field_error("/evaluator_type", "invalid_format", "Pick the phrase or judge question template")
        ]
    if not isinstance(config, Mapping):
        return {}, [field_error("/config", "required", "Fill in the check")]
    return CUSTOM_TYPES[evaluator_type].validate_config(config, judge_models)


async def _name_conflict(session: AsyncSession, name: str) -> None:
    if name in BUILTINS:
        raise ProblemError(
            409, "evaluator_name_taken", "Name in use", f"{name} is the name of a built-in check."
        )
    taken = await session.execute(
        select(func.count())
        .select_from(EvaluatorRow)
        .where(EvaluatorRow.kind == "custom", EvaluatorRow.name == name, EvaluatorRow.deleted_at.is_(None))
    )
    if taken.scalar_one():
        raise ProblemError(
            409, "evaluator_name_taken", "Name in use", f"You already have a custom check named {name}"
        )


async def create_custom(
    session: AsyncSession,
    workspace_id: str,
    user_id: str | None,
    body: Mapping[str, Any],
    judge_models: Sequence[str],
) -> tuple[EvaluatorRow, dict[str, Any]]:
    errors: list[dict[str, str]] = []
    display = body.get("display_name")
    if not isinstance(display, str) or not 1 <= len(display.strip()) <= 80:
        errors.append(field_error("/display_name", "out_of_range", "Name the check in 1 to 80 characters"))
        display = ""
    name = body.get("name") or derive_name(display)
    if not isinstance(name, str) or not NAME_RE.match(name):
        pointer = "/name" if body.get("name") else "/display_name"
        errors.append(field_error(pointer, "invalid_format", "Use a name that starts with a letter"))
    description = body.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > 500):
        errors.append(
            field_error("/description", "out_of_range", "Keep the description under 500 characters")
        )
    description = description.strip() or None if isinstance(description, str) else None
    config, config_errors = validate_config(body.get("evaluator_type"), body.get("config"), judge_models)
    errors += config_errors
    if errors:
        raise validation_failed(errors)
    await _name_conflict(session, name)
    count = await session.execute(
        select(func.count())
        .select_from(EvaluatorRow)
        .where(EvaluatorRow.kind == "custom", EvaluatorRow.deleted_at.is_(None))
    )
    if count.scalar_one() >= MAX_CUSTOM:
        raise ProblemError(
            409,
            "evaluator_limit",
            "Limit reached",
            f"A workspace can have at most {MAX_CUSTOM} custom checks.",
        )
    now = datetime.now(UTC)
    evaluator_type = str(body["evaluator_type"])
    row = EvaluatorRow(
        id=new_id("evl"),
        workspace_id=workspace_id,
        kind="custom",
        evaluator_type=evaluator_type,
        name=name,
        display_name=display.strip(),
        description=description,
        scope="call",
        cost_class=CUSTOM_TYPES[evaluator_type].cost_class,
        output_kind="class",
        agent_types=["single_prompt", "flow"],
        settings_schema={"fields": []},
        score_range={"min": 0, "max": 1},
        current_version=1,
        enabled_by_default=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    session.add(
        EvaluatorVersion(
            evaluator_id=row.id,
            version=1,
            workspace_id=workspace_id,
            definition=config,
            judge_model=config.get("judge_model"),
            created_by=user_id,
            created_at=now,
        )
    )
    await session.flush()
    return row, config


async def update_custom(
    session: AsyncSession,
    evaluator_id: str,
    user_id: str | None,
    body: Mapping[str, Any],
    judge_models: Sequence[str],
) -> tuple[EvaluatorRow, dict[str, Any]]:
    row = await get_evaluator(session, evaluator_id)
    if row.kind != "custom":
        raise forbidden("Built-in checks cannot be edited.", "builtin_evaluator")
    if row.deleted_at is not None:
        raise not_found("evaluator")
    if not body:
        raise validation_failed([field_error("/", "required", "Send at least one field to change")])
    current = (await current_definitions(session, [row])).get(row.id, {})
    errors: list[dict[str, str]] = []
    if "display_name" in body:
        display = body["display_name"]
        if not isinstance(display, str) or not 1 <= len(display.strip()) <= 80:
            errors.append(
                field_error("/display_name", "out_of_range", "Name the check in 1 to 80 characters")
            )
    if (
        "description" in body
        and body["description"] is not None
        and (not isinstance(body["description"], str) or len(body["description"]) > 500)
    ):
        errors.append(
            field_error("/description", "out_of_range", "Keep the description under 500 characters")
        )
    config = current
    if "config" in body:
        config, config_errors = validate_config(row.evaluator_type, body["config"], judge_models)
        errors += config_errors
    if errors:
        raise validation_failed(errors)
    now = datetime.now(UTC)
    if "display_name" in body:
        row.display_name = body["display_name"].strip()
    if "description" in body:
        description = body["description"]
        row.description = description.strip() or None if isinstance(description, str) else None
    if "config" in body and config != current:
        row.current_version += 1
        session.add(
            EvaluatorVersion(
                evaluator_id=row.id,
                version=row.current_version,
                workspace_id=row.workspace_id,
                definition=config,
                judge_model=config.get("judge_model"),
                created_by=user_id,
                created_at=now,
            )
        )
    row.updated_at = now
    await session.flush()
    return row, config


async def delete_custom(session: AsyncSession, evaluator_id: str) -> None:
    row = await get_evaluator(session, evaluator_id)
    if row.kind != "custom":
        raise forbidden("Built-in checks cannot be deleted.", "builtin_evaluator")
    if row.deleted_at is None:
        row.deleted_at = row.updated_at = datetime.now(UTC)
        await session.flush()
