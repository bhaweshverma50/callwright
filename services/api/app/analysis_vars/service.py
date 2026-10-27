"""Analysis variable CRUD, ordering and soft delete (007 T018; FR-001, FR-045, FR-046).

Names are validated, never rewritten (the web form normalises what the operator types). Deleted
variables stop being extracted; values already captured on calls are kept.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.analysis_vars.models import AnalysisVariable
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import new_id

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
NAME_RULE = "Use lowercase letters, digits and underscores, starting with a letter"
TYPES = ("boolean", "string", "number", "choice")
MAX_VARIABLES = 25
MIN_CHOICES, MAX_CHOICES = 2, 20


def validate_fields(
    *, name: Any, type: Any, description: Any, choices: Any, partial: Mapping[str, bool] | None = None
) -> list[dict[str, str]]:
    """Field errors for a variable's final state (FR-001, FR-046). ``partial`` limits the name and
    description checks to fields actually sent (PATCH)."""
    sent = partial if partial is not None else {"name": True, "description": True}
    errors: list[dict[str, str]] = []
    if sent.get("name", False) and (not isinstance(name, str) or not NAME_RE.match(name)):
        errors.append(field_error("/name", "invalid_format", NAME_RULE))
    if type not in TYPES:
        errors.append(
            field_error("/type", "invalid_format", "Pick yes/no, text, number or one of a fixed set")
        )
    if sent.get("description", False) and (
        not isinstance(description, str) or not 1 <= len(description.strip()) <= 500
    ):
        errors.append(
            field_error("/description", "out_of_range", "Describe what to capture in 1 to 500 characters")
        )
    if type == "choice":
        if not isinstance(choices, list) or not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
            errors.append(field_error("/choices", "out_of_range", "Add 2 to 20 choices"))
        elif any(not isinstance(c, str) or not 1 <= len(c.strip()) <= 64 for c in choices):
            errors.append(field_error("/choices", "out_of_range", "Each choice needs 1 to 64 characters"))
        elif len({c.strip() for c in choices}) != len(choices):
            errors.append(field_error("/choices", "invalid_format", "Choices must be unique"))
    elif choices is not None and type in TYPES:
        errors.append(
            field_error("/choices", "invalid_format", "Choices are only accepted for the fixed-set type")
        )
    return errors


def variable_view(v: AnalysisVariable) -> dict[str, Any]:
    return {
        "id": v.id,
        "agent_id": v.agent_id,
        "name": v.name,
        "type": v.type,
        "description": v.description,
        "choices": list(v.choices) if v.choices is not None else None,
        "position": v.position,
        "created_at": v.created_at.isoformat(),
        "updated_at": v.updated_at.isoformat(),
    }


async def require_agent(session: AsyncSession, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise not_found("agent")
    return agent


async def active_variables(session: AsyncSession, agent_id: str) -> list[AnalysisVariable]:
    rows = await session.execute(
        select(AnalysisVariable)
        .where(AnalysisVariable.agent_id == agent_id, AnalysisVariable.deleted_at.is_(None))
        .order_by(AnalysisVariable.position, AnalysisVariable.created_at)
    )
    return list(rows.scalars())


def _name_taken(name: str) -> ProblemError:
    return ProblemError(
        409, "variable_name_taken", "Name in use", f"This agent already has a variable named {name}."
    )


async def create_variable(
    session: AsyncSession, workspace_id: str, agent_id: str, body: Mapping[str, Any]
) -> AnalysisVariable:
    await require_agent(session, agent_id)
    errors = validate_fields(
        name=body.get("name"),
        type=body.get("type"),
        description=body.get("description"),
        choices=body.get("choices"),
    )
    if errors:
        raise validation_failed(errors)
    existing = await active_variables(session, agent_id)
    if any(v.name == body["name"] for v in existing):
        raise _name_taken(body["name"])
    if len(existing) >= MAX_VARIABLES:
        raise ProblemError(
            409, "variable_limit", "Limit reached", f"An agent can have at most {MAX_VARIABLES} variables."
        )
    now = datetime.now(UTC)
    position = (max((v.position for v in existing), default=-1)) + 1
    choices = [c.strip() for c in body["choices"]] if body.get("choices") is not None else None
    row = AnalysisVariable(
        id=new_id("var"),
        workspace_id=workspace_id,
        agent_id=agent_id,
        name=body["name"],
        type=body["type"],
        description=body["description"].strip(),
        choices=choices,
        position=position,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def get_variable(session: AsyncSession, variable_id: str) -> AnalysisVariable:
    row = await session.get(AnalysisVariable, variable_id)
    if row is None or row.deleted_at is not None:
        raise not_found("analysis variable")
    return row


async def update_variable(
    session: AsyncSession, variable_id: str, body: Mapping[str, Any]
) -> AnalysisVariable:
    row = await get_variable(session, variable_id)
    if not body:
        raise validation_failed([field_error("/", "required", "Send at least one field to change")])
    new_type = body.get("type", row.type)
    # Changing away from the fixed-set type drops the choices unless the request sends some.
    if "choices" in body:
        choices = body["choices"]
    elif new_type != "choice":
        choices = None
    else:
        choices = list(row.choices) if row.choices is not None else None
    errors = validate_fields(
        name=body.get("name", row.name),
        type=new_type,
        description=body.get("description", row.description),
        choices=choices,
        partial={"name": "name" in body, "description": "description" in body},
    )
    if errors:
        raise validation_failed(errors)
    if "name" in body and body["name"] != row.name:
        clash = await session.execute(
            select(func.count())
            .select_from(AnalysisVariable)
            .where(
                AnalysisVariable.agent_id == row.agent_id,
                AnalysisVariable.deleted_at.is_(None),
                AnalysisVariable.name == body["name"],
                AnalysisVariable.id != row.id,
            )
        )
        if clash.scalar_one():
            raise _name_taken(body["name"])
        row.name = body["name"]
    if "description" in body:
        row.description = body["description"].strip()
    row.type = new_type
    row.choices = [c.strip() for c in choices] if choices is not None else None
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


async def reorder(session: AsyncSession, agent_id: str, variable_ids: Sequence[str]) -> None:
    await require_agent(session, agent_id)
    rows = await active_variables(session, agent_id)
    by_id = {v.id: v for v in rows}
    if len(variable_ids) != len(set(variable_ids)) or set(variable_ids) != set(by_id):
        raise validation_failed(
            [field_error("/variable_ids", "invalid_format", "List every active variable of the agent once")]
        )
    now = datetime.now(UTC)
    for position, variable_id in enumerate(variable_ids):
        by_id[variable_id].position = position
        by_id[variable_id].updated_at = now
    await session.flush()


async def delete_variable(session: AsyncSession, variable_id: str) -> None:
    row = await get_variable(session, variable_id)
    row.deleted_at = datetime.now(UTC)
    await session.flush()


def snapshot(variables: Sequence[AnalysisVariable]) -> list[dict[str, Any]]:
    return [
        {
            "id": v.id,
            "name": v.name,
            "type": v.type,
            "description": v.description,
            "choices": list(v.choices) if v.choices is not None else None,
        }
        for v in variables
    ]
