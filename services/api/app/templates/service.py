"""Template catalog reads (T073, T074, research R16).

Templates are global rows written by the sync job (``templates/jobs.py``) from
``templates/seed/*.yaml``. A template's ``config`` is a partial AgentConfig plus ``agent_name``
(the suggested agent name); ``agents.offered.template_overlay`` turns it into an agent config.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import escape_like
from app.templates.models import Template
from app.voices.catalog import DEFAULT_LANGUAGE

CATEGORIES: dict[str, str] = {
    "automotive": "Automotive",
    "banking": "Banking",
    "ecommerce": "E-commerce",
    "healthcare": "Healthcare",
    "telecom": "Telecom",
    "insurance": "Insurance",
    "real_estate": "Real estate",
    "hospitality": "Travel and hospitality",
    "logistics": "Logistics and delivery",
    "utilities": "Utilities",
}


def _filtered(
    category: str | None, search: str | None, direction: str | None, agent_type: str | None
) -> Select[Any]:
    query = select(Template).where(Template.is_active.is_(True))
    if category:
        query = query.where(Template.category == category)
    if direction:
        query = query.where(Template.direction == direction)
    if agent_type:
        query = query.where(Template.agent_type == agent_type)
    if search and search.strip():
        pattern = f"%{escape_like(search.strip())}%"
        query = query.where(or_(Template.name.ilike(pattern), Template.description.ilike(pattern)))
    return query


async def list_templates(
    session: AsyncSession,
    *,
    category: str | None = None,
    search: str | None = None,
    direction: str | None = None,
    agent_type: str | None = None,
) -> list[Template]:
    query = _filtered(category, search, direction, agent_type)
    rows = await session.execute(query.order_by(Template.sort_order, Template.id))
    return list(rows.scalars())


async def get_template(
    session: AsyncSession, template_id: str, *, active_only: bool = True
) -> Template | None:
    template = await session.get(Template, template_id)
    if template is None or (active_only and not template.is_active):
        return None
    return template


async def categories(
    session: AsyncSession,
    *,
    search: str | None = None,
    direction: str | None = None,
    agent_type: str | None = None,
) -> list[dict[str, Any]]:
    """Per-category counts under the same filters as the list, except the category itself, so
    the chips show how many templates each category would give with the other filters on."""
    matching = _filtered(None, search, direction, agent_type).subquery()
    rows = await session.execute(select(matching.c.category, func.count()).group_by(matching.c.category))
    counts = {str(cat): int(n) for cat, n in rows}
    return [
        {"id": cat, "label": label, "count": counts[cat]}
        for cat, label in CATEGORIES.items()
        if counts.get(cat)
    ]


def summary_json(template: Template) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "icon": template.icon,
        "direction": template.direction,
        "agent_type": template.agent_type,
        "language": str(template.config.get("language") or DEFAULT_LANGUAGE),
    }


def detail_json(template: Template) -> dict[str, Any]:
    return {**summary_json(template), "config": copy.deepcopy(template.config)}
