"""/v1/test-runs and the runner's /v1/internal/test-runs endpoints (008 T036;
contracts/test_runs.yaml)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.core.auth import CurrentPrincipal, Principal, require_service
from app.core.errors import not_found, problem_responses
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import is_valid_id, path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.simulator import dispatch
from app.test_runs import jobs, service
from app.test_runs.schemas import CaseResult, OverrideBody, StartRun

router = APIRouter(tags=["test_runs"])
internal_router = APIRouter(tags=["internal"], dependencies=[Depends(require_service)])

TestRunId = Annotated[str, Depends(path_id("trn", "test run", "test_run_id"))]
TestCaseId = Annotated[str, Depends(path_id("tc", "test case", "test_case_id"))]
START = "POST /v1/test-runs"
EXPORT_FORMAT = "callwright.test_run_results.v1"


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


async def _enqueue(request: Request, name: str, *args: Any) -> None:
    queue = getattr(request.app.state, "jobs", None)
    if queue is not None:
        await queue.enqueue(name, *args)


@router.get("/test-runs")
async def list_runs(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: Annotated[str, Query(pattern=r"^agt_")],
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_runs(session, agent_id, page=page, page_size=page_size)
        return {**page_meta(total, page, page_size), "items": [service.run_view(r) for r in rows]}


@router.post("/test-runs", status_code=202, responses=problem_responses(402, 409, 422))
async def start_run(
    request: Request,
    principal: CurrentPrincipal,
    body: StartRun,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    state = request.app.state

    async def handler() -> tuple[int, Any]:
        async with _tx(request, principal) as session:
            run, case_ids = await service.start_run(
                session,
                state.settings,
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                body=body.model_dump(mode="json", exclude_none=True),
            )
            view = service.run_view(run)
        for case_id in case_ids:
            await _enqueue(request, jobs.DISPATCH_TEST_CASE, principal.workspace_id, run.id, case_id)
        return 202, view

    return await run_idempotent(
        state.db,
        workspace_id=principal.workspace_id,
        endpoint=START,
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/test-runs/{test_run_id}", responses=problem_responses(404))
async def get_run(request: Request, principal: CurrentPrincipal, test_run_id: TestRunId) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        run = await service.get_run(session, test_run_id)
        results = await service.results_of(session, run.id)
        return {**service.run_view(run), "results": [service.result_view(r) for r in results]}


@router.post("/test-runs/{test_run_id}/cancel", responses=problem_responses(404, 409))
async def cancel_run(request: Request, principal: CurrentPrincipal, test_run_id: TestRunId) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        run, released = await service.cancel(session, test_run_id)
        view = service.run_view(run)
    for case_id in released:
        await dispatch.release(
            request.app.state.redis, principal.workspace_id, jobs.holder(test_run_id, case_id)
        )
    return view


@router.patch("/test-runs/{test_run_id}/results/{test_case_id}", responses=problem_responses(404, 409))
async def override_result(
    request: Request,
    principal: CurrentPrincipal,
    test_run_id: TestRunId,
    test_case_id: TestCaseId,
    body: OverrideBody,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        result, run = await service.override(
            session, test_run_id, test_case_id, body.override_status, body.override_note
        )
        return {"result": service.result_view(result), "run": service.run_view(run)}


@router.get("/test-runs/{test_run_id}/export", responses=problem_responses(404))
async def export_run(request: Request, principal: CurrentPrincipal, test_run_id: TestRunId) -> JSONResponse:
    async with _tx(request, principal) as session:
        run = await service.get_run(session, test_run_id)
        results = await service.results_of(session, run.id)
        document = {
            "format": EXPORT_FORMAT,
            "run": service.run_view(run),
            "results": [service.result_view(r) for r in results],
        }
    filename = f"test_run_{run.id}_results.json"
    return JSONResponse(document, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Internal (voice-worker textsim role, service token) -----------------------------------------


async def run_workspace(request: Request, test_run_id: str) -> str:
    if not is_valid_id(test_run_id, "trn"):
        raise not_found("test run")
    async with request.app.state.db.transaction() as session:
        workspace_id = (
            await session.execute(text("select test_runs_workspace_for(:id)"), {"id": test_run_id})
        ).scalar()
    if workspace_id is None:
        raise not_found("test run")
    return str(workspace_id)


@internal_router.get(
    "/internal/test-runs/{test_run_id}/cases/{test_case_id}/spec", responses=problem_responses(404, 409)
)
async def internal_case_spec(request: Request, test_run_id: str, test_case_id: str) -> dict[str, Any]:
    workspace_id = await run_workspace(request, test_run_id)
    async with request.app.state.db.transaction(workspace_id=workspace_id) as session:
        return await service.case_spec(session, test_run_id, test_case_id)


@internal_router.post(
    "/internal/test-runs/{test_run_id}/cases/{test_case_id}/result",
    status_code=204,
    responses=problem_responses(404),
)
async def internal_case_result(
    request: Request, test_run_id: str, test_case_id: str, body: CaseResult
) -> Response:
    workspace_id = await run_workspace(request, test_run_id)
    async with request.app.state.db.transaction(workspace_id=workspace_id) as session:
        outcome = await service.record_result(
            session, test_run_id, test_case_id, body.model_dump(mode="json")
        )
    await dispatch.release(request.app.state.redis, workspace_id, jobs.holder(test_run_id, test_case_id))
    if outcome == "judge":
        await _enqueue(request, jobs.JUDGE_RESULT, workspace_id, test_run_id, test_case_id)
    return Response(status_code=204)
