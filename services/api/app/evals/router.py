"""/v1 eval settings, call evaluations, reruns and verdict diffs (007 T039, T041; contracts/evals.yaml)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app.calls.models import Call
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import ProblemError, not_found, problem_responses
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id, require_id
from app.evals import service, verdict_diff, views
from app.evals.jobs import EVALUATE_CALL, start_evaluation
from app.evals.runner import AlreadyRunning, already_running
from app.evals.schemas import RerunBody, SettingPut
from app.evaluators.settings import judge_models

router = APIRouter(tags=["evals"])

AgentId = Annotated[str, Depends(path_id("agt", "agent", "agent_id"))]
EvaluatorId = Annotated[str, Depends(path_id("evl", "evaluator", "evaluator_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]
DONE_STATES = ("completed", "voicemail")


def _judge_models(request: Request) -> list[str]:
    return list(judge_models(request.app.state.settings))


@router.get("/agents/{agent_id}/eval-settings", responses=problem_responses(404))
async def list_settings(request: Request, principal: CurrentPrincipal, agent_id: AgentId) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return {"items": await service.list_settings(session, agent_id, _judge_models(request))}


@router.put("/agents/{agent_id}/eval-settings/{evaluator_id}", responses=problem_responses(404, 409, 422))
async def put_setting(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: AgentId,
    evaluator_id: EvaluatorId,
    body: SettingPut,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return await service.put_setting(
            session,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            agent_id=agent_id,
            evaluator_id=evaluator_id,
            body=body.model_dump(),
            judge_models=_judge_models(request),
        )


async def evaluations_body(session: Any, call_id: str, include_history: bool) -> dict[str, Any]:
    runs = await views.call_runs(session, call_id)
    current, history = views.split_current(runs)
    status, passes, fails = views.status_of(current)
    body: dict[str, Any] = {
        "call_id": call_id,
        "eval_status": status,
        "pass_count": passes,
        "fail_count": fails,
        "runs": views.ordered(await views.views_for(session, current)),
    }
    if include_history:
        body["history"] = await views.views_for(session, history)
    return body


@router.get("/calls/{call_id}/evaluations", responses=problem_responses(404))
async def get_evaluations(
    request: Request,
    principal: CurrentPrincipal,
    call_id: CallId,
    include_history: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        if await session.get(Call, call_id) is None:
            raise not_found("call")
        return await evaluations_body(session, call_id, include_history)


@router.post("/calls/{call_id}/evaluations/rerun", status_code=202, responses=problem_responses(409, 422))
async def rerun(
    request: Request,
    principal: CurrentPrincipal,
    call_id: CallId,
    body: Annotated[RerunBody | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    evaluator_ids = body.evaluator_ids if body else None

    async def handler() -> tuple[int, Any]:
        async with principal_tx(request, principal) as session:
            call = await session.get(Call, call_id)
            if call is None:
                raise not_found("call")
            if call.status not in DONE_STATES:
                raise ProblemError(
                    409,
                    "call_not_completed",
                    "Call not finished",
                    "Checks can run once the call has finished.",
                )
            try:
                start = await start_evaluation(
                    session,
                    call,
                    trigger="rerun",
                    idempotency_key=f"rerun:{key}",
                    evaluator_ids=evaluator_ids,
                    user_id=principal.user_id,
                )
            except AlreadyRunning as exc:
                raise already_running() from exc
            group_id = start.group.run_group_id
            active = start.group.status == "active"
            result = {"run_group_id": group_id, "runs": await views.views_for(session, start.runs)}
        if active:
            await request.app.state.jobs.enqueue(
                EVALUATE_CALL, principal.workspace_id, call_id, group_id, job_id=f"evaluate:{group_id}"
            )
        return 202, result

    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint=f"evals_rerun:{call_id}",
        key=key,
        body={"evaluator_ids": evaluator_ids},
        handler=handler,
        instance=request.url.path,
    )


@router.get("/evals/verdict-diff", responses=problem_responses(404))
async def get_verdict_diff(
    request: Request,
    principal: CurrentPrincipal,
    base_call_id: Annotated[str, Query()],
    other_call_id: Annotated[str, Query()],
) -> dict[str, Any]:
    require_id(base_call_id, "call", "call")
    require_id(other_call_id, "call", "call")
    async with principal_tx(request, principal) as session:
        for call_id in (base_call_id, other_call_id):
            if await session.get(Call, call_id) is None:
                raise not_found("call")
        rows = await verdict_diff.diffs(session, base_call_id, other_call_id)
    items = []
    for d, display, versions in rows:
        delta = (
            d.right_score - d.left_score if d.left_score is not None and d.right_score is not None else None
        )
        items.append(
            {
                "evaluator_id": d.evaluator_id,
                "evaluator_name": d.evaluator_name,
                "display_name": display,
                "base": {
                    "verdict": d.left_verdict,
                    "score": d.left_score,
                    "evaluator_version": versions["left"],
                },
                "other": {
                    "verdict": d.right_verdict,
                    "score": d.right_score,
                    "evaluator_version": versions["right"],
                },
                "score_delta": round(delta, 4) if delta is not None else None,
                "other_rationale": d.right_rationale,
            }
        )
    return {"items": items}
