"""Outbound calls and compliance settings (contracts/outbound.yaml, 010 T031, T075 to T077)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.core.auth import CurrentPrincipal
from app.core.errors import ProblemError, field_error, problem_responses, validation_failed
from app.core.ids import path_id
from app.core.pagination import PageParam
from app.outbound import calling_hours, dnc
from app.outbound import service as outbound
from app.outbound.schemas import CallingHoursUpdate, DncEntryCreate, OutboundCallRequest
from app.phone_numbers.validation import E164

router = APIRouter(tags=["outbound"])

DncId = Annotated[str, Depends(path_id("dnc", "do-not-call entry", "dnc_id"))]
ListSize = Annotated[int, Query(ge=1, le=100)]


def outbound_deps(request: Request) -> outbound.OutboundDeps:
    state = request.app.state
    return outbound.OutboundDeps(
        db=state.db,
        settings=state.settings,
        sip=state.sip,
        livekit=state.livekit,
        catalog=state.adapter_catalog,
        jobs=getattr(state, "jobs", None),
        redis=state.redis,
    )


@router.post(
    "/outbound-calls", status_code=202, responses=problem_responses(400, 401, 402, 403, 409, 422, 429, 503)
)
async def create_outbound_call(
    body: OutboundCallRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    return await outbound.start_outbound_call(
        outbound_deps(request), principal, body, idempotency_key, request.url.path
    )


# Do-not-call list -------------------------------------------------------------------------------


@router.get("/dnc-entries", responses=problem_responses(401))
async def list_dnc_entries(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: ListSize = 50,
    number: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return await dnc.list_entries(session, page=page, page_size=page_size, number=number)


@router.post("/dnc-entries", status_code=201, responses=problem_responses(401, 409, 422))
async def create_dnc_entry(
    body: DncEntryCreate, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        entry = await dnc.add_entry(
            session, principal.workspace_id, principal.user_id, body.number, body.default_region, body.note
        )
        return JSONResponse(dnc.to_out(entry), status_code=201)


@router.delete("/dnc-entries/{dnc_id}", status_code=204, responses=problem_responses(401, 404))
async def delete_dnc_entry(dnc_id: DncId, request: Request, principal: CurrentPrincipal) -> Response:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        await dnc.remove_entry(session, dnc_id)
    return Response(status_code=204)


@router.post("/dnc-entries/import", responses=problem_responses(401, 409, 413, 422))
async def import_dnc_entries(
    request: Request,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    default_region: Annotated[str | None, Form(pattern="^[A-Z]{2}$")] = None,
) -> dict[str, Any]:
    data = await file.read(dnc.MAX_BYTES + 1)
    try:
        parsed = dnc.parse_csv(data, default_region)
    except dnc.CsvError as exc:
        raise exc.problem() from None
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        return await dnc.import_csv(session, principal.workspace_id, principal.user_id, parsed)


# Calling hours ----------------------------------------------------------------------------------


@router.get("/outbound-calling-hours", responses=problem_responses(401))
async def get_calling_hours(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return calling_hours.view(await calling_hours.get_windows(session, principal.workspace_id))


@router.put("/outbound-calling-hours", responses=problem_responses(401, 422))
async def put_calling_hours(
    body: CallingHoursUpdate, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        try:
            row = await calling_hours.put_windows(
                session, principal.workspace_id, principal.user_id, body.windows
            )
        except calling_hours.InvalidWindow as exc:
            raise ProblemError(
                422,
                "invalid_window",
                "Invalid calling hours",
                str(exc),
                errors=[field_error(exc.pointer, "invalid_window", str(exc))],
            ) from None
        return calling_hours.view(row)


# Decision log -----------------------------------------------------------------------------------


@router.get("/outbound-policy-decisions", responses=problem_responses(401, 422))
async def list_outbound_policy_decisions(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: ListSize = 50,
    reason: Literal["dnc_listed", "outside_calling_hours"] | None = None,
    to_number: Annotated[str | None, Query(max_length=16)] = None,
    since: datetime | None = None,
) -> dict[str, Any]:
    if to_number is not None and not E164.match(to_number):
        raise validation_failed(
            [field_error("/to_number", "invalid_format", "Use E.164, for example +14155550123.")]
        )
    async with request.app.state.db.transaction(workspace_id=principal.workspace_id) as session:
        return await outbound.list_decisions(
            session, page=page, page_size=page_size, reason=reason, to_number=to_number, since=since
        )
