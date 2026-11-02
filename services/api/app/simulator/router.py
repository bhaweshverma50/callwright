"""/v1/simulations/preflight, /v1/simulation-runs and /v1/experiments (008 T053, T065;
contracts/simulator.yaml)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import problem_responses
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.simulator import comparison, dispatch, jobs, preflight, service
from app.simulator.schemas import PreflightBody, StartExperimentBody, StartRunBody
from app.simulator.targets import require_agent

router = APIRouter(tags=["simulator"])

RunId = Annotated[str, Depends(path_id("srun", "simulation run", "simulation_run_id"))]
ExperimentId = Annotated[str, Depends(path_id("exp", "simulation batch", "experiment_id"))]
StatusQuery = Annotated[str | None, Query(pattern="^(pending|running|completed|failed|cancelled)$")]
START_RUN = "POST /v1/simulation-runs"
START_EXPERIMENT = "POST /v1/experiments"


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


@router.post("/simulations/preflight", responses=problem_responses(409, 422))
async def simulation_preflight(
    request: Request, principal: CurrentPrincipal, body: PreflightBody
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        agent = await require_agent(session, body.agent_id, pointer="/agent_id")
        return await preflight.preflight(
            session,
            agent,
            mode=body.mode,
            target=body.target.model_dump(exclude_none=True),
            base_call_ids=body.base_call_ids,
            dataset_id=body.dataset_id,
            simulator_model=request.app.state.settings.simulator_model,
        )


@router.get("/simulation-runs")
async def list_runs(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: str | None = None,
    base_call_id: str | None = None,
    experiment_id: str | None = None,
    standalone: bool | None = None,
    status: StatusQuery = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_runs(
            session,
            agent_id=agent_id,
            base_call_id=base_call_id,
            experiment_id=experiment_id,
            standalone=standalone,
            status=status,
            page=page,
            page_size=page_size,
        )
        return {**page_meta(total, page, page_size), "items": await service.views(session, rows)}


@router.post("/simulation-runs", status_code=202, responses=problem_responses(402, 409, 422))
async def start_run(
    request: Request,
    principal: CurrentPrincipal,
    body: StartRunBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    state = request.app.state

    async def handler() -> tuple[int, Any]:
        async with _tx(request, principal) as session:
            run = await service.start_run(
                session,
                state.settings,
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                body=body.model_dump(mode="json", exclude_none=True),
            )
            [view] = await service.views(session, [run])
        await jobs.enqueue_runs(getattr(state, "jobs", None), principal.workspace_id, [run.id])
        return 202, view

    return await run_idempotent(
        state.db,
        workspace_id=principal.workspace_id,
        endpoint=START_RUN,
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/simulation-runs/{simulation_run_id}", responses=problem_responses(404))
async def get_run(request: Request, principal: CurrentPrincipal, simulation_run_id: RunId) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        run = await service.get_run(session, simulation_run_id)
        [view] = await service.views(session, [run])
        return view


@router.get("/simulation-runs/{simulation_run_id}/comparison", responses=problem_responses(404, 409))
async def get_comparison(
    request: Request, principal: CurrentPrincipal, simulation_run_id: RunId
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        run = await service.get_run(session, simulation_run_id)
        return await comparison.build_comparison(session, run)


@router.post("/simulation-runs/{simulation_run_id}/cancel", responses=problem_responses(404, 409))
async def cancel_run(
    request: Request, principal: CurrentPrincipal, simulation_run_id: RunId
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        run = await service.cancel_run(session, simulation_run_id)
        [view] = await service.views(session, [run])
        experiment_id = run.experiment_id
    await dispatch.release(request.app.state.redis, principal.workspace_id, simulation_run_id)
    if experiment_id:
        await jobs.fire_if_finished(request.app.state.db, principal.workspace_id, experiment_id)
    return view


@router.get("/experiments")
async def list_experiments(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: str | None = None,
    source: Annotated[str | None, Query(pattern="^(call_selection|dataset|issue_validation|api)$")] = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_experiments(
            session, agent_id=agent_id, source=source, page=page, page_size=page_size
        )
        names = await service.agent_names(session, [e.agent_id for e in rows])
        return {
            **page_meta(total, page, page_size),
            "items": [service.experiment_view(e, agent_name=names.get(e.agent_id)) for e in rows],
        }


@router.post("/experiments", status_code=202, responses=problem_responses(402, 409, 422))
async def start_experiment(
    request: Request,
    principal: CurrentPrincipal,
    body: StartExperimentBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    state = request.app.state

    async def handler() -> tuple[int, Any]:
        async with _tx(request, principal) as session:
            exp, run_ids = await service.start_experiment(
                session,
                state.settings,
                workspace_id=principal.workspace_id,
                agent_id=body.agent_id,
                mode=body.mode,
                target=body.target.model_dump(exclude_none=True) if body.target else None,
                base_call_ids=body.base_call_ids,
                dataset_id=body.dataset_id,
                run_settings_raw=body.settings.model_dump(exclude_none=True) if body.settings else None,
                name=body.name,
                user_id=principal.user_id,
            )
            names = await service.agent_names(session, [exp.agent_id])
            view = service.experiment_view(exp, agent_name=names.get(exp.agent_id))
        await jobs.enqueue_runs(getattr(state, "jobs", None), principal.workspace_id, run_ids)
        return 202, view

    return await run_idempotent(
        state.db,
        workspace_id=principal.workspace_id,
        endpoint=START_EXPERIMENT,
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/experiments/{experiment_id}", responses=problem_responses(404))
async def get_experiment(
    request: Request, principal: CurrentPrincipal, experiment_id: ExperimentId
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        exp = await service.get_experiment(session, experiment_id)
        names = await service.agent_names(session, [exp.agent_id])
        return service.experiment_view(exp, agent_name=names.get(exp.agent_id))


@router.get("/experiments/{experiment_id}/runs", responses=problem_responses(404))
async def list_experiment_runs(
    request: Request,
    principal: CurrentPrincipal,
    experiment_id: ExperimentId,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        await service.get_experiment(session, experiment_id)
        rows, total = await service.list_runs(
            session,
            agent_id=None,
            base_call_id=None,
            experiment_id=experiment_id,
            standalone=None,
            status=None,
            page=page,
            page_size=page_size,
        )
        return {**page_meta(total, page, page_size), "items": await service.views(session, rows)}


@router.get("/experiments/{experiment_id}/scorecard", responses=problem_responses(404, 422))
async def get_scorecard(
    request: Request,
    principal: CurrentPrincipal,
    experiment_id: ExperimentId,
    baseline: Annotated[str, Query(pattern="^(original|experiment)$")] = "original",
    baseline_experiment_id: Annotated[str | None, Query(pattern=r"^exp_")] = None,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        exp, card = await comparison.scorecard_for(
            session, experiment_id, baseline=baseline, baseline_experiment_id=baseline_experiment_id
        )
        return comparison.scorecard_view(exp.id, card, baseline_experiment_id)


@router.post("/experiments/{experiment_id}/cancel", responses=problem_responses(404))
async def cancel_experiment(
    request: Request, principal: CurrentPrincipal, experiment_id: ExperimentId
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        exp, released = await service.cancel_experiment(session, experiment_id)
        names = await service.agent_names(session, [exp.agent_id])
        view = service.experiment_view(exp, agent_name=names.get(exp.agent_id))
    for run_id in released:
        await dispatch.release(request.app.state.redis, principal.workspace_id, run_id)
    await jobs.fire_if_finished(request.app.state.db, principal.workspace_id, experiment_id)
    return view
