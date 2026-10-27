"""/v1 analysis variables and call analysis (007 T021; contracts/analysis_vars.yaml)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse

from app.analysis_vars import service
from app.analysis_vars.jobs import RERUN_ANALYSIS, ensure_row
from app.analysis_vars.models import CallAnalysis
from app.analysis_vars.schemas import VariableInput, VariableOrder, VariablePatch
from app.billing import service as billing
from app.calls.models import Call
from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import ProblemError, not_found, problem_responses
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id

router = APIRouter(tags=["analysis_vars"])

AgentId = Annotated[str, Depends(path_id("agt", "agent", "agent_id"))]
VariableId = Annotated[str, Depends(path_id("var", "analysis variable", "variable_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]
STALE_RUNNING = timedelta(minutes=5)
DONE_STATES = ("completed", "voicemail")


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


@router.get("/agents/{agent_id}/analysis-variables", responses=problem_responses(404))
async def list_variables(request: Request, principal: CurrentPrincipal, agent_id: AgentId) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        await service.require_agent(session, agent_id)
        rows = await service.active_variables(session, agent_id)
    return {"items": [service.variable_view(v) for v in rows]}


@router.post(
    "/agents/{agent_id}/analysis-variables", status_code=201, responses=problem_responses(409, 422)
)
async def create_variable(
    request: Request, principal: CurrentPrincipal, agent_id: AgentId, body: VariableInput
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        row = await service.create_variable(session, principal.workspace_id, agent_id, body.model_dump())
        return service.variable_view(row)


@router.put("/agents/{agent_id}/analysis-variables/order", status_code=204, responses=problem_responses(422))
async def reorder_variables(
    request: Request, principal: CurrentPrincipal, agent_id: AgentId, body: VariableOrder
) -> Response:
    async with _tx(request, principal) as session:
        await service.reorder(session, agent_id, body.variable_ids)
    return Response(status_code=204)


@router.patch("/analysis-variables/{variable_id}", responses=problem_responses(404, 409, 422))
async def update_variable(
    request: Request, principal: CurrentPrincipal, variable_id: VariableId, body: VariablePatch
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        row = await service.update_variable(session, variable_id, body.model_dump(exclude_unset=True))
        return service.variable_view(row)


@router.delete("/analysis-variables/{variable_id}", status_code=204, responses=problem_responses(404))
async def delete_variable(request: Request, principal: CurrentPrincipal, variable_id: VariableId) -> Response:
    async with _tx(request, principal) as session:
        await service.delete_variable(session, variable_id)
    return Response(status_code=204)


def analysis_view(call: Call, row: CallAnalysis | None, current: dict[str, Any]) -> dict[str, Any]:
    """``current`` maps active variable ids to their names (for renamed and deleted labels)."""
    if row is None:
        # Calls analysed before 007 existed, or not reached by the pipeline yet.
        done = call.summary is not None
        values = [
            {"variable_id": None, "name": k, "type": _type_of(v), "value": v, "status": "current"}
            for k, v in (call.analysis or {}).items()
        ]
        return {
            "call_id": call.id,
            "status": "completed" if done else "pending",
            "skip_reason": None,
            "error": None,
            "model": None,
            "summary": call.summary,
            "sentiment": call.sentiment,
            "values": values,
            "analyzed_at": None,
        }
    out_values = []
    for var in row.variable_snapshot or []:
        name = str(var["name"])
        if var.get("id") not in current:
            status = "deleted"
        elif current[var["id"]] != name:
            status = "renamed"
        else:
            status = "current"
        out_values.append(
            {
                "variable_id": var.get("id"),
                "name": name,
                "type": var["type"],
                "value": (row.values or {}).get(name),
                "status": status,
            }
        )
    return {
        "call_id": call.id,
        "status": row.status,
        "skip_reason": row.skip_reason,
        "error": row.error,
        "model": row.model,
        "summary": row.summary,
        "sentiment": row.sentiment,
        "values": out_values if row.status == "completed" else [],
        "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
    }


def _type_of(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "string"


async def _load(session: Any, call_id: str) -> tuple[Call, CallAnalysis | None, dict[str, Any]]:
    call = await session.get(Call, call_id)
    if call is None:
        raise not_found("call")
    row = await session.get(CallAnalysis, call_id)
    current = {v.id: v.name for v in await service.active_variables(session, call.agent_id)}
    return call, row, current


@router.get("/calls/{call_id}/analysis", responses=problem_responses(404))
async def get_analysis(request: Request, principal: CurrentPrincipal, call_id: CallId) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        call, row, current = await _load(session, call_id)
        return analysis_view(call, row, current)


@router.post("/calls/{call_id}/analysis/rerun", status_code=202, responses=problem_responses(402, 409))
async def rerun_analysis(
    request: Request,
    principal: CurrentPrincipal,
    call_id: CallId,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)

    async def handler() -> tuple[int, Any]:
        async with _tx(request, principal) as session:
            call, row, current = await _load(session, call_id)
            if call.status not in DONE_STATES:
                raise ProblemError(
                    409,
                    "call_not_completed",
                    "Call not finished",
                    "Analysis can run once the call has finished.",
                )
            if await billing.get_balance(session, principal.workspace_id) <= 0:
                raise billing.insufficient_credit("Add funds to re-run the analysis.")
            row = row or await ensure_row(session, call)
            now = datetime.now(UTC)
            if row.status == "running" and row.updated_at > now - STALE_RUNNING:
                raise ProblemError(
                    409, "analysis_running", "Analysis running", "The analysis is already running."
                )
            row.attempt += 1
            row.status = "running"
            row.updated_at = now
            await session.flush()
            body = analysis_view(call, row, current)
        await request.app.state.jobs.enqueue(RERUN_ANALYSIS, principal.workspace_id, call_id)
        return 202, body

    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint=f"analysis_rerun:{call_id}",
        key=key,
        body={},
        handler=handler,
        instance=request.url.path,
    )
