"""/v1/test-categories and /v1/test-cases (008 T031; contracts/test_cases.yaml)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from app.billing import service as billing
from app.core.auth import CurrentPrincipal, principal_tx
from app.core.errors import ProblemError, field_error, problem_responses, validation_failed
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id
from app.core.money import SIX
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.llms.runtime import runtime
from app.test_cases import generate as drafting
from app.test_cases import import_format, service
from app.test_cases.schemas import CategoryCreate, GenerateBody, ImportBody, TestCaseCreate, TestCaseUpdate
from app.testing.charges import charge_run
from app.testing.targets import require_agent, resolve_target, runnable_problem

router = APIRouter(tags=["test_cases"])

TestCaseId = Annotated[str, Depends(path_id("tc", "test case", "test_case_id"))]
AgentQuery = Annotated[str, Query(pattern=r"^agt_")]
GENERATE = "POST /v1/test-cases/generate"


def generator_model(request: Request) -> str:
    settings = request.app.state.settings
    return str(settings.testcase_generator_model or settings.simulator_model)


@router.get("/test-categories")
async def list_categories(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        rows = await service.list_categories(session, principal.workspace_id)
        return {"items": [service.category_view(c) for c in rows]}


@router.post("/test-categories", status_code=201, responses=problem_responses(409, 422))
async def create_category(
    request: Request, principal: CurrentPrincipal, body: CategoryCreate
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        category = await service.create_category(
            session, principal.workspace_id, name=body.name, slug=body.slug, color=body.color
        )
        return service.category_view(category)


@router.delete("/test-categories/{slug}", status_code=204, responses=problem_responses(404, 409))
async def delete_category(request: Request, principal: CurrentPrincipal, slug: str) -> Response:
    async with principal_tx(request, principal) as session:
        await service.delete_category(session, principal.workspace_id, slug)
    return Response(status_code=204)


@router.get("/test-cases")
async def list_cases(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: AgentQuery,
    category: str | None = None,
    last_status: Annotated[str | None, Query(pattern="^(passed|failed|error|not_run)$")] = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        rows, total = await service.list_cases(
            session, agent_id, category=category, last_status=last_status, page=page, page_size=page_size
        )
        return {**page_meta(total, page, page_size), "items": [service.case_view(c) for c in rows]}


@router.post("/test-cases", status_code=201, responses=problem_responses(409, 422))
async def create_case(request: Request, principal: CurrentPrincipal, body: TestCaseCreate) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        case = await service.create_case(session, principal.workspace_id, body.model_dump())
        return service.case_view(case)


@router.post("/test-cases/import", responses=problem_responses(422))
async def import_cases(request: Request, principal: CurrentPrincipal, body: ImportBody) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        document = {"format": body.format, "test_cases": body.test_cases} if body.format else body.test_cases
        return await service.import_cases(
            session, principal.workspace_id, body.agent_id, document, dry_run=body.dry_run
        )


@router.get("/test-cases/export")
async def export_cases(
    request: Request, principal: CurrentPrincipal, agent_id: AgentQuery, template: bool = False
) -> JSONResponse:
    if template:
        document = import_format.template_file()
        filename = "test_cases_template.json"
    else:
        async with principal_tx(request, principal) as session:
            cases = [service.case_view(c) for c in await service.all_cases(session, agent_id)]
        document = import_format.export_file(agent_id, cases)
        filename = f"test_cases_{agent_id}.json"
    return JSONResponse(document, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/test-cases/generate", responses=problem_responses(402, 409, 503))
async def generate_cases(
    request: Request,
    principal: CurrentPrincipal,
    body: GenerateBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    state = request.app.state
    model = generator_model(request)

    async def handler() -> tuple[int, Any]:
        async with principal_tx(request, principal) as session:
            agent = await require_agent(session, body.agent_id, pointer="/agent_id")
            categories = await service.list_categories(session, principal.workspace_id)
            if body.category is not None and body.category not in {c.slug for c in categories}:
                raise validation_failed([field_error("/category", "invalid_format", "Choose a category")])
            target = await resolve_target(session, agent, None, default="draft", allow_variant=False)
            problem = runnable_problem(agent.type, target.config)
            if problem is not None:
                raise problem
            if await billing.get_balance(session, principal.workspace_id) <= 0:
                raise billing.insufficient_credit("Add funds to draft test cases.")
        try:
            drafts, usage = await drafting.generate(
                runtime().llm,
                model,
                agent,
                target.config,
                categories,
                category=body.category,
                count=body.count,
                guidance=body.guidance,
                timeout_s=state.settings.sim_timeout_s,
            )
        except drafting.GenerationFailed as exc:
            raise ProblemError(
                503, "generation_unavailable", "Drafting failed", f"{exc}. Try again in a moment."
            ) from exc
        async with principal_tx(request, principal) as session:
            charge = await charge_run(
                session,
                workspace_id=principal.workspace_id,
                run_id=f"testgen_{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}",
                feature_key="testing.generate",
                usage=usage.as_usage(),
                ref_type="agent",
                ref_id=agent.id,
            )
        return 200, {"drafts": drafts, "cost_usd": float(charge.billable_usd.quantize(SIX))}

    return await run_idempotent(
        state.db,
        workspace_id=principal.workspace_id,
        endpoint=GENERATE,
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/test-cases/{test_case_id}", responses=problem_responses(404))
async def get_case(request: Request, principal: CurrentPrincipal, test_case_id: TestCaseId) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        return service.case_view(await service.get_case(session, test_case_id))


@router.patch("/test-cases/{test_case_id}", responses=problem_responses(404, 409, 422))
async def update_case(
    request: Request, principal: CurrentPrincipal, test_case_id: TestCaseId, body: TestCaseUpdate
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise validation_failed([field_error("", "required", "Change at least one field")])
    async with principal_tx(request, principal) as session:
        case = await service.update_case(session, principal.workspace_id, test_case_id, changes)
        return service.case_view(case)


@router.delete("/test-cases/{test_case_id}", status_code=204, responses=problem_responses(404))
async def delete_case(request: Request, principal: CurrentPrincipal, test_case_id: TestCaseId) -> Response:
    async with principal_tx(request, principal) as session:
        await service.delete_case(session, test_case_id)
    return Response(status_code=204)
