"""The text runner's endpoints (008 T054; contracts/simulator.yaml, service token).

``GET /v1/internal/simulation-runs/{id}/spec`` hands the runner the snapshot, settings,
variables and, for replays, the caller turns, recorded tool outputs and original node path; the
run becomes ``running`` and its simulated call is created. ``POST .../result`` records the
outcome (see ``service.record_result``). The workspace comes from the run row, never the body.
"""

from __future__ import annotations

from typing import Any

from callwright_contract.textsim import SimResult
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.core.auth import require_service
from app.core.errors import not_found, problem_responses
from app.core.ids import is_valid_id
from app.simulator import jobs, service

router = APIRouter(tags=["internal"], dependencies=[Depends(require_service)])


async def run_workspace(request: Request, run_id: str) -> str:
    if not is_valid_id(run_id, "srun"):
        raise not_found("simulation run")
    async with request.app.state.db.transaction() as session:
        workspace_id = (
            await session.execute(text("select simulation_runs_workspace_for(:id)"), {"id": run_id})
        ).scalar()
    if workspace_id is None:
        raise not_found("simulation run")
    return str(workspace_id)


@router.get("/internal/simulation-runs/{simulation_run_id}/spec", responses=problem_responses(404, 409))
async def internal_spec(request: Request, simulation_run_id: str) -> dict[str, Any]:
    workspace_id = await run_workspace(request, simulation_run_id)
    async with request.app.state.db.transaction(workspace_id=workspace_id) as session:
        spec = await service.spec_for(session, simulation_run_id)
    return spec.model_dump(mode="json", exclude_unset=True)


@router.post(
    "/internal/simulation-runs/{simulation_run_id}/result", status_code=204, responses=problem_responses(404)
)
async def internal_result(request: Request, simulation_run_id: str, body: SimResult) -> Response:
    state = request.app.state
    workspace_id = await run_workspace(request, simulation_run_id)
    group = None
    async with state.db.transaction(workspace_id=workspace_id) as session:
        run = await service.record_result(session, simulation_run_id, body.model_dump(mode="json"))
        if run is not None:
            group = await service.ensure_base_evaluation(session, run)
            experiment_id, base_call_id = run.experiment_id, run.base_call_id
    if run is not None:
        await jobs.after_result(
            state.db,
            state.redis,
            getattr(state, "jobs", None),
            workspace_id,
            simulation_run_id,
            experiment_id,
            group,
            base_call_id,
        )
    return Response(status_code=204)
