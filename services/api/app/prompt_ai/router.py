"""POST /v1/prompt-ai/generate (contracts/prompt_ai.yaml; T082)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from app.core.auth import CurrentPrincipal
from app.core.errors import problem_responses
from app.llms.client import LlmClient
from app.prompt_ai import service
from app.prompt_ai.schemas import GenerateRequest

router = APIRouter(tags=["prompt_ai"])


@router.post(
    "/prompt-ai/generate",
    responses={**problem_responses(401, 402, 422, 429), 504: {"description": "Assistant timed out"}},
)
async def generate_prompt(
    body: GenerateRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> dict[str, Any]:
    state = request.app.state
    client: LlmClient = getattr(state, "llm_client", None) or LlmClient(state.settings)
    return await service.generate(
        state.db,
        state.redis,
        state.settings,
        client,
        workspace_id=principal.workspace_id,
        request=body,
        idempotency_key=idempotency_key,
    )
