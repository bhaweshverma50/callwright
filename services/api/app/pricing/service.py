"""Catalog lookup by instant, quotes and admin publishing (T068, research R3, R15).

``quote()`` is the in-process entry point for 002 (cost card) and 003 (running cost); the HTTP
quote endpoint and ``billing.service.charge_call`` use the same function, so every price comes
from ``engine.price``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, field_error, validation_failed
from app.pricing import engine
from app.pricing.models import CatalogVersion, PricingRate


class CatalogUnavailable(Exception):
    """No catalog version is in effect at the requested instant."""


def _to_rate(row: PricingRate) -> engine.Rate:
    return engine.Rate(
        component=row.component,
        provider=row.provider,
        model=row.model,
        label=row.label,
        rate_per_min_usd=Decimal(row.rate_per_min_usd),
        bundles=tuple(engine.Bundle(str(b["unit"]), int(b["per_min"])) for b in row.bundles),
        unit="k_tokens" if row.unit == "k_tokens" else "minute",
    )


async def _load_version(session: AsyncSession, version: CatalogVersion) -> engine.Catalog:
    rows = (
        await session.execute(
            select(PricingRate).where(PricingRate.version == version.version).order_by(PricingRate.id)
        )
    ).scalars()
    return engine.Catalog(
        version=version.version,
        effective_from=version.effective_from,
        rates=tuple(_to_rate(r) for r in rows),
    )


async def catalog_at(session: AsyncSession, at: datetime | None = None) -> engine.Catalog:
    """The version with the greatest ``effective_from <= at`` (default now)."""
    instant = at or datetime.now(UTC)
    version = (
        await session.execute(
            select(CatalogVersion)
            .where(CatalogVersion.effective_from <= instant)
            .order_by(CatalogVersion.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise CatalogUnavailable(instant.isoformat())
    return await _load_version(session, version)


async def catalog_now(session: AsyncSession) -> engine.Catalog | None:
    """The catalog in effect now, or ``None`` before the first version (prices shown as unknown)."""
    try:
        return await catalog_at(session)
    except CatalogUnavailable:
        return None


async def catalog_version(session: AsyncSession, version: int) -> engine.Catalog:
    row = await session.get(CatalogVersion, version)
    if row is None:
        raise CatalogUnavailable(f"version {version}")
    return await _load_version(session, row)


async def quote(
    session: AsyncSession,
    components: engine.Components,
    usage: engine.Usage | None = None,
    at: datetime | None = None,
) -> engine.Quote:
    return engine.price(components, usage, await catalog_at(session, at))


# Admin -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionSummary:
    version: int
    effective_from: datetime
    effective_to: datetime | None
    notes: str | None
    created_at: datetime


async def list_versions(
    session: AsyncSession, *, page: int, page_size: int
) -> tuple[list[VersionSummary], int]:
    total = int((await session.execute(select(func.count()).select_from(CatalogVersion))).scalar_one())
    all_rows = list(
        (
            await session.execute(select(CatalogVersion).order_by(CatalogVersion.effective_from.desc()))
        ).scalars()
    )
    summaries: list[VersionSummary] = []
    next_from: datetime | None = None
    for row in all_rows:
        summaries.append(
            VersionSummary(row.version, row.effective_from, next_from, row.notes, row.created_at)
        )
        next_from = row.effective_from
    start = (page - 1) * page_size
    return summaries[start : start + page_size], total


@dataclass(frozen=True)
class EntryInput:
    component: str
    provider: str
    model: str | None
    label: str
    rate_per_min_usd: Decimal
    bundles: tuple[engine.Bundle, ...]


def validate_entries(entries: Sequence[EntryInput]) -> list[dict[str, str]]:
    """Field errors for a complete catalog row set (R3): unique keys, bundles only on llm/tts,
    exactly one platform row."""
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    platform_rows = 0
    for i, entry in enumerate(entries):
        key = (entry.component, entry.provider, entry.model or "")
        if key in seen:
            errors.append(
                field_error(
                    f"/entries/{i}", "duplicate", "This component, provider and model appears more than once."
                )
            )
        seen.add(key)
        if entry.bundles and entry.component not in engine.SURCHARGEABLE:
            errors.append(
                field_error(
                    f"/entries/{i}/bundles", "invalid_format", "Only llm and tts entries may carry bundles."
                )
            )
        if entry.component == "platform":
            platform_rows += 1
        if entry.rate_per_min_usd < 0:
            errors.append(
                field_error(f"/entries/{i}/rate_per_min_usd", "out_of_range", "Rates cannot be negative.")
            )
    if platform_rows != 1:
        errors.append(field_error("/entries", "invalid_format", "Exactly one platform entry is required."))
    return errors


def validate_effective_from(
    effective_from: datetime, current_from: datetime | None, now: datetime
) -> list[dict[str, str]]:
    if effective_from.tzinfo is None:
        return [field_error("/effective_from", "invalid_format", "Include a time zone offset.")]
    if effective_from <= now:
        return [field_error("/effective_from", "out_of_range", "The effective time must be in the future.")]
    if current_from is not None and effective_from <= current_from:
        return [
            field_error(
                "/effective_from",
                "out_of_range",
                "The effective time must be later than the latest published version.",
            )
        ]
    return []


async def publish_version(
    admin_session: AsyncSession,
    *,
    effective_from: datetime,
    entries: Sequence[EntryInput],
    notes: str | None,
    published_by: str | None,
    now: datetime | None = None,
) -> engine.Catalog:
    """Publish a complete row set as the next version (admin connection only).

    Internal ``embedding`` rows are not part of the public per-minute catalog, so the latest
    version's embedding rows are carried forward unchanged.
    """
    await admin_session.execute(select(func.pg_advisory_xact_lock(7_001_001)))
    latest = (
        await admin_session.execute(select(CatalogVersion).order_by(CatalogVersion.version.desc()).limit(1))
    ).scalar_one_or_none()
    errors = validate_entries(entries) + validate_effective_from(
        effective_from, latest.effective_from if latest else None, now or datetime.now(UTC)
    )
    if errors:
        raise validation_failed(errors)
    new_version = (latest.version if latest else 0) + 1
    admin_session.add(
        CatalogVersion(
            version=new_version, effective_from=effective_from, notes=notes, published_by=published_by
        )
    )
    await admin_session.flush()
    for entry in entries:
        admin_session.add(
            PricingRate(
                version=new_version,
                component=entry.component,
                provider=entry.provider,
                model=entry.model,
                label=entry.label,
                rate_per_min_usd=entry.rate_per_min_usd,
                unit="minute",
                bundles=[{"unit": b.unit, "per_min": b.per_min} for b in entry.bundles],
            )
        )
    if latest is not None:
        carried = (
            await admin_session.execute(
                select(PricingRate).where(
                    PricingRate.version == latest.version, PricingRate.component == "embedding"
                )
            )
        ).scalars()
        for row in list(carried):
            admin_session.add(
                PricingRate(
                    version=new_version,
                    component=row.component,
                    provider=row.provider,
                    model=row.model,
                    label=row.label,
                    rate_per_min_usd=row.rate_per_min_usd,
                    unit=row.unit,
                    bundles=list(row.bundles),
                )
            )
    await admin_session.flush()
    return await catalog_version(admin_session, new_version)


def unpriced_problem(components: Sequence[str]) -> ProblemError:
    return ProblemError(
        409,
        "pricing_unavailable",
        "Price unavailable",
        f"No catalog rate for: {', '.join(components)}.",
    )
