"""Test categories and cases (008 T029, T090; FR-001 to FR-006, FR-032).

* Seed categories (out of scope, bad behaviour, identity, prompt injection, guardrails) exist
  in every workspace: the migration wrote them for existing workspaces and ``ensure_seeds``
  adds them on first use for new ones. Seeds cannot be deleted; a custom category cannot be
  deleted while cases use it.
* Categories carry a palette colour and are listed alphabetically by name, ignoring case.
* A blank case name becomes "<Category name> test". Cases are unique per agent by their
  normalised prompt and expected behaviour (``import_format.dedupe_key``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import new_id
from app.test_cases.import_format import ImportResult, dedupe_key, parse_import
from app.test_cases.models import TestCase, TestCategory
from app.testing.targets import require_agent

# Design palette for category chips (FR-032); seeds take fixed entries.
CATEGORY_PALETTE: tuple[str, ...] = (
    "#3346e8",
    "#7a3cff",
    "#e0457b",
    "#e89a1c",
    "#12805c",
    "#0e8fb3",
    "#c2281b",
    "#5e6287",
)
SEED_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("out_of_scope", "Out of scope", "#e89a1c"),
    ("bad_behaviour", "Bad behaviour", "#e0457b"),
    ("identity", "Identity", "#7a3cff"),
    ("prompt_injection", "Prompt injection", "#c2281b"),
    ("guardrails", "Guardrails", "#12805c"),
)
SLUG = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def category_view(c: TestCategory) -> dict[str, Any]:
    return {"slug": c.slug, "name": c.name, "color": c.color, "is_seed": c.is_seed}


def case_view(c: TestCase) -> dict[str, Any]:
    return {
        "test_case_id": c.id,
        "agent_id": c.agent_id,
        "name": c.name,
        "category": c.category_slug,
        "user_prompt": c.user_prompt,
        "expected_behaviour": c.expected_behaviour,
        "dynamic_variables": dict(c.dynamic_variables or {}),
        "last_status": c.last_status,
        "last_run_id": c.last_run_id,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


# Categories ------------------------------------------------------------------------------------


async def ensure_seeds(session: AsyncSession, workspace_id: str) -> None:
    for slug, name, color in SEED_CATEGORIES:
        await session.execute(
            text(
                "insert into test_categories (workspace_id, slug, name, color, is_seed) "
                "values (:ws, :slug, :name, :color, true) on conflict do nothing"
            ),
            {"ws": workspace_id, "slug": slug, "name": name, "color": color},
        )


async def list_categories(session: AsyncSession, workspace_id: str) -> list[TestCategory]:
    await ensure_seeds(session, workspace_id)
    rows = await session.execute(
        select(TestCategory).order_by(func.lower(TestCategory.name), TestCategory.slug)
    )
    return list(rows.scalars())


def slug_for(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"c_{slug}".rstrip("_")
    if len(slug) < 2:
        slug = f"{slug}_x"
    return slug[:40].rstrip("_")


async def create_category(
    session: AsyncSession, workspace_id: str, *, name: str, slug: str | None, color: str | None
) -> TestCategory:
    existing = await list_categories(session, workspace_id)
    name = name.strip()
    if not name:
        raise validation_failed([field_error("/name", "required", "Enter a name")])
    slug = slug or slug_for(name)
    if not SLUG.match(slug):
        raise validation_failed(
            [field_error("/slug", "invalid_format", "Use 2 to 40 lowercase letters, digits or underscores")]
        )
    if color is not None and color not in CATEGORY_PALETTE:
        raise validation_failed(
            [field_error("/color", "invalid_format", "Choose one of the palette colours")]
        )
    if any(c.slug == slug or c.name.casefold() == name.casefold() for c in existing):
        raise ProblemError(
            409, "category_exists", "Category exists", "A category with that name already exists."
        )
    used = {c.color for c in existing}
    chosen = color or next((c for c in CATEGORY_PALETTE if c not in used), CATEGORY_PALETTE[0])
    category = TestCategory(workspace_id=workspace_id, slug=slug, name=name, color=chosen, is_seed=False)
    session.add(category)
    await session.flush()
    return category


async def delete_category(session: AsyncSession, workspace_id: str, slug: str) -> None:
    await ensure_seeds(session, workspace_id)
    category = await session.get(TestCategory, (workspace_id, slug))
    if category is None:
        raise not_found("test category")
    if category.is_seed:
        raise ProblemError(
            409, "seed_category", "Built-in category", "Built-in categories cannot be deleted."
        )
    used = (
        await session.execute(
            select(func.count()).select_from(TestCase).where(TestCase.category_slug == slug)
        )
    ).scalar_one()
    if used:
        raise ProblemError(
            409,
            "category_in_use",
            "Category in use",
            f"{used} test case{'s' if used != 1 else ''} use this category. Move or delete them first.",
        )
    await session.delete(category)


async def _category_names(session: AsyncSession, workspace_id: str) -> dict[str, str]:
    return {c.slug: c.name for c in await list_categories(session, workspace_id)}


# Cases ---------------------------------------------------------------------------------------


def default_name(category_name: str) -> str:
    return f"{category_name} test"[:120]


def _duplicate() -> ProblemError:
    return ProblemError(
        409,
        "duplicate_test_case",
        "Duplicate test case",
        "This agent already has a test case with the same caller line and expected behaviour.",
    )


async def _dedupe_taken(session: AsyncSession, agent_id: str, key: str, exclude: str | None = None) -> bool:
    query = select(TestCase.id).where(TestCase.agent_id == agent_id, TestCase.dedupe_key == key)
    if exclude:
        query = query.where(TestCase.id != exclude)
    return (await session.execute(query)).first() is not None


async def create_case(session: AsyncSession, workspace_id: str, body: Mapping[str, Any]) -> TestCase:
    agent = await require_agent(session, str(body["agent_id"]), pointer="/agent_id")
    names = await _category_names(session, workspace_id)
    category = str(body["category"])
    if category not in names:
        raise validation_failed([field_error("/category", "invalid_format", "Choose a category")])
    prompt = str(body["user_prompt"]).strip()
    expected = str(body["expected_behaviour"]).strip()
    errors = []
    if not prompt:
        errors.append(field_error("/user_prompt", "required", "Enter what the caller says"))
    if not expected:
        errors.append(field_error("/expected_behaviour", "required", "Describe the expected behaviour"))
    if errors:
        raise validation_failed(errors)
    key = dedupe_key(prompt, expected)
    if await _dedupe_taken(session, agent.id, key):
        raise _duplicate()
    name = str(body.get("name") or "").strip() or default_name(names[category])
    now = datetime.now(UTC)
    case = TestCase(
        id=new_id("tc"),
        workspace_id=workspace_id,
        agent_id=agent.id,
        name=name,
        category_slug=category,
        user_prompt=prompt,
        expected_behaviour=expected,
        dynamic_variables=dict(body.get("dynamic_variables") or {}),
        dedupe_key=key,
        created_at=now,
        updated_at=now,
    )
    session.add(case)
    await session.flush()
    return case


async def get_case(session: AsyncSession, case_id: str) -> TestCase:
    case = await session.get(TestCase, case_id)
    if case is None:
        raise not_found("test case")
    return case


async def update_case(
    session: AsyncSession, workspace_id: str, case_id: str, body: Mapping[str, Any]
) -> TestCase:
    case = await get_case(session, case_id)
    if "category" in body:
        names = await _category_names(session, workspace_id)
        if body["category"] not in names:
            raise validation_failed([field_error("/category", "invalid_format", "Choose a category")])
        case.category_slug = str(body["category"])
    for key in ("name", "user_prompt", "expected_behaviour"):
        if key in body:
            value = str(body[key]).strip()
            if not value:
                raise validation_failed([field_error(f"/{key}", "required", "This field cannot be empty")])
            setattr(case, key, value)
    if "dynamic_variables" in body:
        case.dynamic_variables = dict(body["dynamic_variables"] or {})
    key = dedupe_key(case.user_prompt, case.expected_behaviour)
    if key != case.dedupe_key and await _dedupe_taken(session, case.agent_id, key, exclude=case.id):
        raise _duplicate()
    case.dedupe_key = key
    case.updated_at = datetime.now(UTC)
    await session.flush()
    return case


async def delete_case(session: AsyncSession, case_id: str) -> None:
    case = await get_case(session, case_id)
    await session.delete(case)


async def list_cases(
    session: AsyncSession,
    agent_id: str,
    *,
    category: str | None = None,
    last_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TestCase], int]:
    where = [TestCase.agent_id == agent_id]
    if category:
        where.append(TestCase.category_slug == category)
    if last_status == "not_run":
        where.append(TestCase.last_status.is_(None))
    elif last_status:
        where.append(TestCase.last_status == last_status)
    total = int(
        (await session.execute(select(func.count()).select_from(TestCase).where(*where))).scalar_one()
    )
    rows = await session.execute(
        select(TestCase)
        .where(*where)
        .order_by(TestCase.created_at, TestCase.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars()), total


async def all_cases(session: AsyncSession, agent_id: str) -> list[TestCase]:
    rows = await session.execute(
        select(TestCase).where(TestCase.agent_id == agent_id).order_by(TestCase.created_at, TestCase.id)
    )
    return list(rows.scalars())


async def import_cases(
    session: AsyncSession, workspace_id: str, agent_id: str, rows: Sequence[Any] | Any, *, dry_run: bool
) -> dict[str, Any]:
    agent = await require_agent(session, agent_id, pointer="/agent_id")
    names = await _category_names(session, workspace_id)
    existing = {c.dedupe_key for c in await all_cases(session, agent.id)}
    result: ImportResult = parse_import(rows, names.keys(), existing=existing)
    if result.fatal:
        raise validation_failed([field_error("/test_cases", "invalid_format", result.fatal)])
    first = next(iter(sorted(names, key=lambda s: names[s].casefold())), None)
    created: list[str] = []
    if not dry_run:
        now = datetime.now(UTC)
        for row in result.valid:
            category = row.category or first  # the first listed category, as in the case editor
            assert category is not None
            case = TestCase(
                id=new_id("tc"),
                workspace_id=workspace_id,
                agent_id=agent.id,
                name=row.name or default_name(names[category]),
                category_slug=category,
                user_prompt=row.user_prompt,
                expected_behaviour=row.expected_behaviour,
                dynamic_variables=row.dynamic_variables,
                dedupe_key=row.key,
                created_at=now,
                updated_at=now,
            )
            session.add(case)
            created.append(case.id)
        await session.flush()
    return {
        "created": len(result.valid),
        "skipped_duplicates": len(result.duplicates),
        "created_ids": created,
        "duplicates": result.duplicates,
        "errors": [{"index": e.index, "field": e.field, "message": e.message} for e in result.errors],
    }
