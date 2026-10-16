"""/v1/pricing (public) and /v1/admin/pricing (contracts/pricing.yaml)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import AdminPrincipal
from app.core.client_ip import client_ip
from app.core.errors import ProblemError, problem_responses, too_many_requests
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.core.rate_limit import RateLimiter
from app.pricing import service
from app.pricing.schemas import PublishRequest, QuoteRequest, catalog_json, quote_json

router = APIRouter(tags=["pricing"])


def _no_catalog() -> ProblemError:
    return ProblemError(
        404, "catalog_unavailable", "Not found", "No pricing catalog is in effect at that time."
    )


@router.get("/pricing/catalog")
async def get_pricing_catalog(
    request: Request, at: Annotated[datetime | None, Query()] = None
) -> JSONResponse:
    async with request.app.state.db.transaction() as session:
        try:
            catalog = await service.catalog_at(session, at)
        except service.CatalogUnavailable as exc:
            raise _no_catalog() from exc
    return JSONResponse(catalog_json(catalog), headers={"Cache-Control": "public, max-age=300"})


@router.post("/pricing/quote", responses=problem_responses(422, 429))
async def quote_price(body: QuoteRequest, request: Request) -> dict[str, Any]:
    ip = client_ip(request)
    limit = request.app.state.settings.quote_rate_limit_per_min
    result = await RateLimiter(request.app.state.redis).hit("quote", ip, limit=limit, window_s=60)
    if not result.allowed:
        raise too_many_requests(result.retry_after_s, "Too many price quotes. Try again in a minute.")
    async with request.app.state.db.transaction() as session:
        try:
            quote = await service.quote(
                session,
                body.components.to_components(),
                body.usage.to_usage() if body.usage is not None else None,
                body.at,
            )
        except service.CatalogUnavailable as exc:
            raise _no_catalog() from exc
    return quote_json(quote)


@router.get("/admin/pricing/versions", tags=["admin"], responses=problem_responses(401, 403))
async def list_pricing_versions(
    request: Request, principal: AdminPrincipal, page: PageParam = 1, page_size: PageSizeParam = 20
) -> dict[str, Any]:
    async with request.app.state.db.admin_transaction() as session:
        items, total = await service.list_versions(session, page=page, page_size=page_size)
    return {
        "items": [
            {
                "version": v.version,
                "effective_from": v.effective_from.isoformat(),
                "effective_to": v.effective_to.isoformat() if v.effective_to else None,
                "notes": v.notes,
                "created_at": v.created_at.isoformat(),
            }
            for v in items
        ],
        **page_meta(total, page, page_size),
    }


@router.post(
    "/admin/pricing/versions", tags=["admin"], status_code=201, responses=problem_responses(401, 403, 422)
)
async def publish_pricing_version(
    body: PublishRequest, request: Request, principal: AdminPrincipal
) -> dict[str, Any]:
    async with request.app.state.db.admin_transaction() as session:
        catalog = await service.publish_version(
            session,
            effective_from=body.effective_from,
            entries=[e.to_input() for e in body.entries],
            notes=body.notes,
            published_by=principal.user_id,
        )
    return catalog_json(catalog)
