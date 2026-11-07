"""/v1 evaluator catalog, custom evaluators and trials (007 T034, T061, T084; contracts/evaluators.yaml).

``/evaluators/judge-models`` and ``/evaluators/trial`` are declared before
``/evaluators/{evaluator_id}`` so they are never read as ids.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from app.billing import service as billing
from app.calls.models import Call
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import ProblemError, not_found, problem_responses, validation_failed
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id, require_id
from app.evaluators import service
from app.evaluators import settings as eval_settings
from app.evaluators.base import EvalTools, Unavailable
from app.evaluators.context import build_context
from app.evaluators.judge import Judge
from app.evaluators.registry import CUSTOM_TYPES, instance_for
from app.evaluators.schemas import CustomInput, CustomPatch, TrialInput
from app.llms.charges import charge_tokens
from app.llms.runtime import runtime

router = APIRouter(tags=["evaluators"])
EvaluatorId = Annotated[str, Depends(path_id("evl", "evaluator", "evaluator_id"))]


def _models(request: Request) -> list[str]:
    return list(eval_settings.judge_models(request.app.state.settings))


@router.get("/evaluators")
async def list_evaluators(
    request: Request,
    principal: CurrentPrincipal,
    kind: Annotated[Literal["builtin", "custom"] | None, Query()] = None,
    agent_type: Annotated[Literal["single_prompt", "flow"] | None, Query()] = None,
    include_deleted: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        rows = await service.list_evaluators(
            session, kind=kind, agent_type=agent_type, include_deleted=include_deleted
        )
        configs = await service.current_definitions(session, [r for r in rows if r.kind == "custom"])
    models = _models(request)
    return {"items": [service.evaluator_view(r, models, configs.get(r.id)) for r in rows]}


@router.post("/evaluators", status_code=201, responses=problem_responses(409, 422))
async def create_custom(request: Request, principal: CurrentPrincipal, body: CustomInput) -> dict[str, Any]:
    models = _models(request)
    async with principal_tx(request, principal) as session:
        row, config = await service.create_custom(
            session, principal.workspace_id, principal.user_id, body.model_dump(exclude_unset=True), models
        )
        return service.evaluator_view(row, models, config)


@router.get("/evaluators/judge-models")
async def judge_models(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    models = _models(request)
    return {
        "items": [
            {"model_id": m, "display_name": m.partition("/")[2] or m, "is_default": i == 0}
            for i, m in enumerate(models)
        ]
    }


@router.post("/evaluators/trial", responses=problem_responses(402, 404, 422))
async def trial(
    request: Request,
    principal: CurrentPrincipal,
    body: TrialInput,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    models = _models(request)

    async def handler() -> tuple[int, Any]:
        config, errors = service.validate_config(body.evaluator_type, body.config, models)
        if errors:
            raise validation_failed(errors)
        require_id(body.call_id, "call", "call")
        judged = CUSTOM_TYPES[body.evaluator_type].cost_class == "llm_judge"
        async with principal_tx(request, principal) as session:
            call = await session.get(Call, body.call_id)
            if call is None:
                raise not_found("call")
            if judged and await billing.get_balance(session, principal.workspace_id) <= 0:
                raise billing.insufficient_credit("Add funds to try a judge question.")
            ctx = await build_context(session, call, run_id=key)
        rt = runtime()
        evaluator = instance_for(body.evaluator_type, config)
        tools = EvalTools(
            judge=Judge.from_settings(rt.llm, rt.settings),
            judge_model=str(config.get("judge_model") or models[0]),
            cutoff=rt.settings.eval_judge_pass_cutoff,
        )
        try:
            outcome = await evaluator.evaluate(ctx, {}, tools)
        except Unavailable as exc:
            raise ProblemError(504, "judge_unavailable", "Judge did not answer", str(exc)) from exc
        charged = None
        if judged and (outcome.input_tokens or outcome.output_tokens):
            async with principal_tx(request, principal) as session:
                trial_charge = await charge_tokens(
                    session,
                    workspace_id=principal.workspace_id,
                    feature_key=evaluator.feature_key,
                    idempotency_key=f"eval_trial:{key}",
                    tokens=outcome.input_tokens + outcome.output_tokens,
                    raw_cost_usd=outcome.raw_cost_usd,
                    ref_type="call",
                    ref_id=call.id,
                )
            charged = float(trial_charge.usage_event.billable_cost_usd)
        item = outcome.items[0]
        return 200, {
            "verdict": item.verdict,
            "score": item.score,
            "rationale": item.rationale or outcome.rationale or "",
            "evidence": {
                "turn_indices": list(item.evidence.get("turn_indices") or []),
                "quote": item.evidence.get("quote"),
            },
            "charged_usd": charged,
        }

    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint="evaluator_trial",
        key=key,
        body=body.model_dump(),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/evaluators/{evaluator_id}", responses=problem_responses(404))
async def get_evaluator(
    request: Request, principal: CurrentPrincipal, evaluator_id: EvaluatorId
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        row = await service.get_evaluator(session, evaluator_id)
        config = (await service.current_definitions(session, [row])).get(row.id)
        versions = await service.versions_of(session, evaluator_id)
    view = service.evaluator_view(row, _models(request), config)
    view["versions"] = [service.version_view(v) for v in versions]
    return view


@router.patch("/evaluators/{evaluator_id}", responses=problem_responses(403, 404, 422))
async def update_custom(
    request: Request, principal: CurrentPrincipal, evaluator_id: EvaluatorId, body: CustomPatch
) -> dict[str, Any]:
    models = _models(request)
    async with principal_tx(request, principal) as session:
        row, config = await service.update_custom(
            session, evaluator_id, principal.user_id, body.model_dump(exclude_unset=True), models
        )
        return service.evaluator_view(row, models, config)


@router.delete("/evaluators/{evaluator_id}", status_code=204, responses=problem_responses(403, 404))
async def delete_custom(request: Request, principal: CurrentPrincipal, evaluator_id: EvaluatorId) -> Response:
    async with principal_tx(request, principal) as session:
        await service.delete_custom(session, evaluator_id)
    return Response(status_code=204)
