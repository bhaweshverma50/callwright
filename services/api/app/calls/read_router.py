"""Call history read side (006 T016, T030, T055, T084, T091; contracts/calls.yaml).

``GET /v1/calls``, ``/calls/live``, ``/calls/export``, ``/calls/{id}``, ``/transcript``,
``/turn-latencies`` and ``/compare``. ``/calls/{id}/flow-transitions`` belongs to 004 and is not
served here. A call from another workspace is a 404 like a missing one (RLS hides it).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from sqlalchemy import select

from app.calls import queries
from app.calls.compare import align_turns, flow_diff, verdict_diffs_json
from app.calls.export import EXPORT_LIMIT, csv_lines, pick_columns
from app.calls.models import Call
from app.calls.ports import registry
from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import ProblemError, field_error, not_found, problem_responses, validation_failed
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta

router = APIRouter(tags=["calls"])
tracer = trace.get_tracer("app.calls.read")

CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]
FILTER_KEYS = (
    "sort",
    "order",
    "call_id",
    "agent_id",
    "status",
    "channel",
    "disconnect_reason",
    "sentiment",
    "from_number",
    "to_number",
    "started_after",
    "started_before",
    "start_date",
    "end_date",
    "tz",
    "label",
    "eval_status",
    "origin",
)


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


def _params(request: Request) -> dict[str, str | None]:
    return {k: request.query_params.get(k) for k in FILTER_KEYS}


@router.get("/calls", responses=problem_responses(401, 422))
async def list_calls(
    request: Request,
    principal: CurrentPrincipal,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    q = queries.parse_list_query(_params(request))
    async with _tx(request, principal) as session:
        items, total = await queries.list_calls(
            session, q, page=page, page_size=page_size, user_id=principal.user_id
        )
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/calls/export", responses=problem_responses(401, 422))
async def export_calls(
    request: Request,
    principal: CurrentPrincipal,
    columns: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    q = queries.parse_list_query(_params(request))
    chosen = pick_columns(columns)
    async with _tx(request, principal) as session:
        total, rows = await queries.iter_export_rows(
            session, q, limit=EXPORT_LIMIT, user_id=principal.user_id
        )
    if total > EXPORT_LIMIT:
        raise ProblemError(
            422,
            "export_too_large",
            "Export too large",
            f"{total:,} calls match. Exports are limited to {EXPORT_LIMIT:,} rows; "
            "narrow the filters and try again.",
            extra={"limit": EXPORT_LIMIT, "total": total},
        )
    filename = f"calls-{date.today().isoformat()}.csv"
    return StreamingResponse(
        csv_lines(rows, chosen),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/calls/live", responses=problem_responses(401))
async def list_live_calls(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    """Calls on air now. Declared before ``/calls/{call_id}`` so "live" is not read as an id."""
    async with _tx(request, principal) as session:
        items, count = await queries.live_calls(session)
    return {"items": items, "count": count, "server_time": datetime.now(UTC).isoformat()}


@router.get("/calls/{call_id}", responses=problem_responses(401, 404))
async def get_call(call_id: CallId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    with tracer.start_as_current_span("calls.detail", attributes={"call_id": call_id}):
        async with _tx(request, principal) as session:
            detail = await queries.call_detail(session, call_id, principal.user_id)
    if detail is None:
        raise not_found("call")
    return detail


@router.get("/calls/{call_id}/transcript", responses=problem_responses(401, 404))
async def get_transcript(call_id: CallId, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        call = await session.get(Call, call_id)
        if call is None:
            raise not_found("call")
        items = await queries.transcript_items(session, call)
    return {"call_id": call_id, "items": items}


@router.get("/calls/{call_id}/turn-latencies", responses=problem_responses(401, 404))
async def get_turn_latencies(
    call_id: CallId, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        call = await session.get(Call, call_id)
        if call is None:
            raise not_found("call")
        turns = await queries.turn_latencies(session, call_id)
    return {"call_id": call_id, "summary": queries.latency_summary(call.latency_stats), "turns": turns}


@router.get("/calls/{call_id}/compare", responses=problem_responses(401, 404, 422))
async def compare_calls(
    call_id: CallId,
    request: Request,
    principal: CurrentPrincipal,
    with_call_id: Annotated[str | None, Query(pattern=r"^call_")] = None,
    with_simulation_run_id: Annotated[str | None, Query(pattern=r"^srun_")] = None,
) -> dict[str, Any]:
    with tracer.start_as_current_span("calls.compare", attributes={"call_id": call_id}):
        async with _tx(request, principal) as session:
            if await session.get(Call, call_id) is None:
                raise ProblemError(404, "not_found", "Not found", "Call not found.")
            if (with_call_id is None) == (with_simulation_run_id is None):
                raise validation_failed(
                    [
                        field_error(
                            "/with_call_id",
                            "required",
                            "Give exactly one of with_call_id or with_simulation_run_id.",
                        )
                    ]
                )
            right_id = with_call_id
            if with_simulation_run_id is not None:
                right_id = (
                    await session.execute(
                        select(Call.id)
                        .where(Call.simulation_run_id == with_simulation_run_id)
                        .order_by(Call.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if right_id is None:
                    raise ProblemError(404, "not_found", "Not found", "Simulation run not found.")
            assert right_id is not None
            left = await queries.call_detail(session, call_id, principal.user_id)
            right = await queries.call_detail(session, right_id, principal.user_id)
            if left is None or right is None:
                raise ProblemError(404, "not_found", "Not found", "Call not found.")
            left_call, right_call = await session.get(Call, call_id), await session.get(Call, right_id)
            assert left_call is not None and right_call is not None
            left_items = await queries.transcript_items(session, left_call)
            right_items = await queries.transcript_items(session, right_call)
            left_flow = await queries.flow_path(session, call_id)
            right_flow = await queries.flow_path(session, right_id)
            verdicts = await registry.quality.verdict_diffs(session, call_id, right_id)
    return {
        "left": left,
        "right": right,
        "right_kind": "simulation" if with_simulation_run_id or right["origin"] == "simulation" else "call",
        "simulation_run_id": with_simulation_run_id or right_call.simulation_run_id,
        "alignment": align_turns(left_items, right_items),
        "flow_diff": flow_diff(left_flow, right_flow),
        "verdict_diffs": verdict_diffs_json(verdicts),
    }
