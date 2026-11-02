"""/v1/datasets (008 T080; contracts/datasets.yaml)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from app.billing import service as billing
from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import field_error, problem_responses, validation_failed
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.datasets import service
from app.datasets.schemas import AddItems, DatasetCreate, DatasetUpdate, EvaluateBody

router = APIRouter(tags=["datasets"])

DatasetId = Annotated[str, Depends(path_id("ds", "dataset", "dataset_id"))]
CallId = Annotated[str, Depends(path_id("call", "call", "call_id"))]
EVALUATE = "POST /v1/datasets/{id}/evaluate"
EVALUATE_CALL = "evaluate_call"


def _tx(request: Request, principal: Principal) -> Any:
    return request.app.state.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id)


@router.get("/datasets")
async def list_datasets(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: str | None = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        rows, total = await service.list_datasets(session, agent_id=agent_id, page=page, page_size=page_size)
        return {**page_meta(total, page, page_size), "items": [service.dataset_view(d, n) for d, n in rows]}


@router.post("/datasets", status_code=201, responses=problem_responses(409, 422))
async def create_dataset(
    request: Request, principal: CurrentPrincipal, body: DatasetCreate
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        dataset = await service.create_dataset(
            session,
            principal.workspace_id,
            name=body.name,
            description=body.description,
            agent_id=body.agent_id,
        )
        view = service.dataset_view(dataset, await service.agent_name(session, dataset.agent_id))
        if body.call_ids:
            view["add_result"] = await service.add_items(session, dataset.id, body.call_ids)
            view["item_count"] = dataset.item_count
        return view


@router.get("/datasets/{dataset_id}", responses=problem_responses(404))
async def get_dataset(request: Request, principal: CurrentPrincipal, dataset_id: DatasetId) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        dataset = await service.get_dataset(session, dataset_id)
        return service.dataset_view(dataset, await service.agent_name(session, dataset.agent_id))


@router.patch("/datasets/{dataset_id}", responses=problem_responses(404, 409, 422))
async def update_dataset(
    request: Request, principal: CurrentPrincipal, dataset_id: DatasetId, body: DatasetUpdate
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise validation_failed([field_error("", "required", "Change the name or the description")])
    async with _tx(request, principal) as session:
        dataset = await service.update_dataset(session, dataset_id, changes)
        return service.dataset_view(dataset, await service.agent_name(session, dataset.agent_id))


@router.delete("/datasets/{dataset_id}", status_code=204, responses=problem_responses(404))
async def delete_dataset(request: Request, principal: CurrentPrincipal, dataset_id: DatasetId) -> Response:
    async with _tx(request, principal) as session:
        await service.delete_dataset(session, dataset_id)
    return Response(status_code=204)


@router.get("/datasets/{dataset_id}/items", responses=problem_responses(404))
async def list_items(
    request: Request,
    principal: CurrentPrincipal,
    dataset_id: DatasetId,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        items, total = await service.list_items(session, dataset_id, page=page, page_size=page_size)
        return {**page_meta(total, page, page_size), "items": items}


@router.post("/datasets/{dataset_id}/items", responses=problem_responses(404, 422))
async def add_items(
    request: Request, principal: CurrentPrincipal, dataset_id: DatasetId, body: AddItems
) -> dict[str, Any]:
    async with _tx(request, principal) as session:
        return await service.add_items(session, dataset_id, body.call_ids)


@router.delete("/datasets/{dataset_id}/items/{call_id}", status_code=204, responses=problem_responses(404))
async def remove_item(
    request: Request, principal: CurrentPrincipal, dataset_id: DatasetId, call_id: CallId
) -> Response:
    async with _tx(request, principal) as session:
        await service.remove_item(session, dataset_id, call_id)
    return Response(status_code=204)


@router.post("/datasets/{dataset_id}/evaluate", status_code=202, responses=problem_responses(402, 404))
async def evaluate_dataset(
    request: Request,
    principal: CurrentPrincipal,
    dataset_id: DatasetId,
    body: Annotated[EvaluateBody | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    state = request.app.state
    options = body or EvaluateBody()

    async def handler() -> tuple[int, Any]:
        async with _tx(request, principal) as session:
            await service.get_dataset(session, dataset_id)
            if await billing.get_balance(session, principal.workspace_id) <= 0:
                raise billing.insufficient_credit("Add funds to run checks.")
            counts, jobs = await service.evaluate(
                session,
                dataset_id,
                only_missing=options.only_missing,
                idempotency_key=key,
                user_id=principal.user_id,
            )
        queue = getattr(state, "jobs", None)
        if queue is not None:
            for call_id, group in jobs:
                await queue.enqueue(
                    EVALUATE_CALL, principal.workspace_id, call_id, group, job_id=f"evaluate:{group}"
                )
        return 202, counts

    return await run_idempotent(
        state.db,
        workspace_id=principal.workspace_id,
        endpoint=EVALUATE,
        key=key,
        body={"dataset_id": dataset_id, **options.model_dump(mode="json")},
        handler=handler,
        instance=request.url.path,
    )
