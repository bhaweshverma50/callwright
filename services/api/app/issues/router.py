"""/v1/issues (009 T022, T032, T041, T046, T050; contracts/issues.yaml).

Paid POSTs take an ``Idempotency-Key``: detect, AI drafting, validate and draft-and-validate.
Model calls run outside database transactions; jobs and batch runs are queued after commit.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.auth import CurrentPrincipal, Principal, principal_tx
from app.core.errors import ProblemError, problem_responses
from app.core.idempotency import require_key, run_idempotent
from app.core.ids import path_id
from app.core.pagination import PageParam, PageSizeParam, page_meta
from app.issues import detection, revisions, service, validation
from app.issues.apply import apply as apply_fix
from app.issues.jobs import DETECT_ISSUES, STALE_DETECTION_S
from app.issues.lifecycle import transition
from app.issues.models import IssueDetectionRun
from app.issues.schemas import (
    ApplyBody,
    CreateFixBody,
    DetectBody,
    DismissBody,
    DraftAndValidateBody,
    ValidationBody,
)

router = APIRouter(tags=["issues"])

IssueId = Annotated[str, Depends(path_id("iss", "issue", "issue_id"))]
DETECT = "POST /v1/issues/detect"
CREATE_FIX = "POST /v1/issues/{id}/fixes"
VALIDATE = "POST /v1/issues/{id}/validate"
DRAFT_AND_VALIDATE = "POST /v1/issues/{id}/draft-and-validate"


def _jobs(request: Request) -> Any:
    return getattr(request.app.state, "jobs", None)


# Detection --------------------------------------------------------------------------------------


@router.post("/issues/detect", status_code=202, responses=problem_responses(402, 409, 422))
async def detect(
    request: Request,
    principal: CurrentPrincipal,
    body: DetectBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)

    async def handler() -> tuple[int, Any]:
        from datetime import UTC, datetime, timedelta

        from app.billing import service as billing
        from app.testing.targets import require_agent

        async with principal_tx(request, principal) as session:
            agent = await require_agent(session, body.agent_id, pointer="/agent_id")
            running = (
                await session.execute(
                    select(IssueDetectionRun)
                    .where(IssueDetectionRun.agent_id == agent.id, IssueDetectionRun.status == "running")
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if running is not None:
                if running.started_at > datetime.now(UTC) - timedelta(seconds=STALE_DETECTION_S):
                    raise ProblemError(
                        409,
                        "detection_running",
                        "Detection in progress",
                        "Issue detection is already running for this agent. Wait for it to finish.",
                    )
                running.status = "failed"
                running.error_message = "Detection took too long and was stopped."
                running.finished_at = datetime.now(UTC)
                await session.flush()
            if await billing.get_balance(session, principal.workspace_id) <= 0:
                raise billing.insufficient_credit("Add funds to run issue detection.")
            run = detection.new_run(
                principal.workspace_id, agent.id, body.window_days, body.include_simulated, principal.user_id
            )
            session.add(run)
            await session.flush()
            view = detection.detection_view(run)
            run_id = str(run.id)
        queue = _jobs(request)
        if queue is not None:
            await queue.enqueue(DETECT_ISSUES, principal.workspace_id, run_id, job_id=f"detect:{run_id}")
        return 202, view

    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint=DETECT,
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/issues/detection")
async def latest_detection(
    request: Request, principal: CurrentPrincipal, agent_id: Annotated[str, Query(pattern="^agt_")]
) -> JSONResponse:
    async with principal_tx(request, principal) as session:
        run = await detection.latest_run(session, agent_id)
        return JSONResponse(detection.detection_view(run) if run is not None else None)


# Issues -----------------------------------------------------------------------------------------


@router.get("/issues")
async def list_issues(
    request: Request,
    principal: CurrentPrincipal,
    agent_id: Annotated[str | None, Query(pattern="^agt_")] = None,
    status: Annotated[str, Query(pattern="^(all|open|validating|validated|applied|dismissed)$")] = "all",
    scope: Annotated[str, Query(pattern="^(real|real_and_simulated)$")] = "real",
    window_days: Annotated[int | None, Query()] = None,
    applied_agent_version_id: Annotated[str | None, Query(pattern="^agv_")] = None,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    if window_days is not None and window_days not in detection.WINDOWS:
        from app.core.errors import field_error, validation_failed

        raise validation_failed(
            [field_error("/window_days", "invalid_format", "Choose 7, 14, 30 or 90 days.")]
        )
    async with principal_tx(request, principal) as session:
        items, total = await service.list_issues(
            session,
            agent_id=agent_id,
            status=status,
            scope=scope,
            window_days=window_days,
            applied_agent_version_id=applied_agent_version_id,
            page=page,
            page_size=page_size,
        )
    return {**page_meta(total, page, page_size), "items": items}


@router.get("/issues/{issue_id}", responses=problem_responses(404))
async def get_issue(request: Request, principal: CurrentPrincipal, issue_id: IssueId) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        issue = await service.get_issue(session, issue_id)
        return await service.detail_view(session, issue)


@router.get("/issues/{issue_id}/samples", responses=problem_responses(404))
async def list_samples(
    request: Request,
    principal: CurrentPrincipal,
    issue_id: IssueId,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        await service.get_issue(session, issue_id)
        rows, total = await service.samples(session, issue_id, page=page, page_size=page_size)
    return {**page_meta(total, page, page_size), "items": [service.sample_view(s) for s in rows]}


# Fixes ------------------------------------------------------------------------------------------


@router.get("/issues/{issue_id}/fixes", responses=problem_responses(404))
async def list_fixes(request: Request, principal: CurrentPrincipal, issue_id: IssueId) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        issue = await service.get_issue(session, issue_id)
        fixes = await service.fixes_of(session, issue.id)
        return {"items": [service.fix_view(f, issue.current_fix_revision) for f in fixes]}


async def _draft(
    request: Request, principal: Principal, issue_id: str, kind: str | None, guidance: str | None
) -> revisions.Drafted:
    async with principal_tx(request, principal) as session:
        await revisions.balance_ok(session, principal.workspace_id)
        data = await revisions.draft_input(session, issue_id, kind, guidance)
    return await revisions.call_drafter(data)


@router.post(
    "/issues/{issue_id}/fixes", status_code=201, responses=problem_responses(402, 404, 409, 422, 502)
)
async def create_fix(
    request: Request,
    principal: CurrentPrincipal,
    issue_id: IssueId,
    body: CreateFixBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    async def manual() -> tuple[int, Any]:
        assert body.kind is not None and body.payload is not None
        async with principal_tx(request, principal) as session:
            fix = await revisions.store(
                session,
                issue_id,
                kind=body.kind,
                given=body.payload,
                rationale="Edited by hand.",
                source="manual",
                guidance=body.guidance,
                user_id=principal.user_id,
            )
            return 201, service.fix_view(fix, fix.revision)

    async def ai() -> tuple[int, Any]:
        drafted = await _draft(request, principal, issue_id, body.kind, body.guidance)
        async with principal_tx(request, principal) as session:
            fix = await revisions.store(
                session,
                issue_id,
                kind=drafted.kind,
                given=drafted.payload,
                rationale=drafted.rationale,
                source="ai",
                guidance=body.guidance,
                user_id=principal.user_id,
                drafted=drafted,
            )
            return 201, service.fix_view(fix, fix.revision)

    if body.mode == "manual":
        status, view = await manual()
        return JSONResponse(view, status_code=status)
    key = require_key(idempotency_key)
    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint=CREATE_FIX.replace("{id}", issue_id),
        key=key,
        body=body.model_dump(mode="json"),
        handler=ai,
        instance=request.url.path,
    )


# Validation -------------------------------------------------------------------------------------


async def _enqueue_runs(request: Request, workspace_id: str, run_ids: list[str]) -> None:
    from app.simulator.jobs import enqueue_runs

    await enqueue_runs(_jobs(request), workspace_id, run_ids)


@router.post(
    "/issues/{issue_id}/validate",
    responses={**problem_responses(402, 404, 409, 422), 202: {"description": "Validation started"}},
)
async def validate(
    request: Request,
    principal: CurrentPrincipal,
    issue_id: IssueId,
    body: ValidationBody | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    body = body or ValidationBody()
    req = validation.Request.of(body.model_dump())
    settings = request.app.state.settings

    async def handler() -> tuple[int, Any]:
        async with principal_tx(request, principal) as session:
            prepared = await validation.prepare(
                session, settings, issue_id, req, lock=not body.dry_run, estimate_only=body.dry_run
            )
            if body.dry_run:
                return 200, prepared.estimate
            started = await validation.start(
                session, settings, prepared, req, auto=False, user_id=principal.user_id
            )
            view = service.validation_view(started.attempt)
        await _enqueue_runs(request, principal.workspace_id, started.run_ids)
        return 202, view

    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint=VALIDATE.replace("{id}", issue_id),
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.post(
    "/issues/{issue_id}/draft-and-validate",
    status_code=202,
    responses=problem_responses(402, 404, 409, 422, 502),
)
async def draft_and_validate(
    request: Request,
    principal: CurrentPrincipal,
    issue_id: IssueId,
    body: DraftAndValidateBody | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = require_key(idempotency_key)
    body = body or DraftAndValidateBody()
    req = validation.Request.of(body.model_dump())
    settings = request.app.state.settings

    async def handler() -> tuple[int, Any]:
        async with principal_tx(request, principal) as session:
            # Refuse early (status, calls) before paying for a draft.
            issue = await service.get_issue(session, issue_id)
            transition(issue.status, "new_revision")
            await validation.select_calls(
                session,
                issue,
                affected_limit=req.affected_limit,
                guard_limit=0,
                min_sample=req.thresholds.min_sample,
            )
        drafted = await _draft(request, principal, issue_id, body.kind, body.guidance)
        async with principal_tx(request, principal) as session:
            fix = await revisions.store(
                session,
                issue_id,
                kind=drafted.kind,
                given=drafted.payload,
                rationale=drafted.rationale,
                source="ai",
                guidance=body.guidance,
                user_id=principal.user_id,
                drafted=drafted,
            )
            if fix.status == "advisory":
                raise validation.advisory_fix()
            prepared = await validation.prepare(session, settings, issue_id, req, lock=True)
            started = await validation.start(
                session, settings, prepared, req, auto=True, user_id=principal.user_id
            )
            view = {
                "fix": service.fix_view(fix, fix.revision),
                "validation": service.validation_view(started.attempt),
            }
        await _enqueue_runs(request, principal.workspace_id, started.run_ids)
        return 202, view

    return await run_idempotent(
        request.app.state.db,
        workspace_id=principal.workspace_id,
        endpoint=DRAFT_AND_VALIDATE.replace("{id}", issue_id),
        key=key,
        body=body.model_dump(mode="json"),
        handler=handler,
        instance=request.url.path,
    )


@router.get("/issues/{issue_id}/validations", responses=problem_responses(404))
async def list_validations(
    request: Request, principal: CurrentPrincipal, issue_id: IssueId
) -> dict[str, Any]:
    async with principal_tx(request, principal) as session:
        await service.get_issue(session, issue_id)
        rows = await service.validations_of(session, issue_id)
        return {"items": [service.validation_view(v) for v in rows]}


@router.post("/issues/{issue_id}/validation/cancel", responses=problem_responses(404, 409))
async def cancel_validation(
    request: Request, principal: CurrentPrincipal, issue_id: IssueId
) -> dict[str, Any]:
    state = request.app.state
    async with principal_tx(request, principal) as session:
        issue = await service.get_issue(session, issue_id, lock=True)
        cancelled = await validation.cancel_running(session, issue)
        if cancelled is None:
            raise ProblemError(
                409,
                "no_validation_running",
                "No validation running",
                "This issue has no validation to cancel.",
            )
    await validation.after_cancel(state.db, state.redis, principal.workspace_id, cancelled)
    async with principal_tx(request, principal) as session:
        return await service.detail_view(session, await service.get_issue(session, issue_id))


# Apply and dismiss -----------------------------------------------------------------------------


@router.post("/issues/{issue_id}/apply", responses=problem_responses(404, 409, 422))
async def apply(
    request: Request, principal: CurrentPrincipal, issue_id: IssueId, body: ApplyBody | None = None
) -> dict[str, Any]:
    body = body or ApplyBody()
    async with principal_tx(request, principal) as session:
        applied = await apply_fix(
            session,
            request.app.state.settings,
            issue_id,
            fix_revision=body.fix_revision,
            publish=body.publish,
            extra_notes=body.release_notes_extra,
            user_id=principal.user_id,
        )
        return {
            "issue": await service.detail_view(session, applied.issue),
            "agent_version_id": applied.agent_version_id,
            "published": applied.published,
            "release_notes": applied.release_notes,
            "tool_copies": applied.tool_copies,
            "draft_updated": applied.draft_updated,
        }


@router.post("/issues/{issue_id}/dismiss", responses=problem_responses(404, 409, 422))
async def dismiss(
    request: Request, principal: CurrentPrincipal, issue_id: IssueId, body: DismissBody
) -> dict[str, Any]:
    state = request.app.state
    async with principal_tx(request, principal) as session:
        _, cancelled = await service.dismiss(
            session,
            issue_id,
            reason=body.reason,
            note=body.note,
            duplicate_of=body.duplicate_of,
            user_id=principal.user_id,
        )
    await validation.after_cancel(state.db, state.redis, principal.workspace_id, cancelled)
    async with principal_tx(request, principal) as session:
        return await service.detail_view(session, await service.get_issue(session, issue_id))
