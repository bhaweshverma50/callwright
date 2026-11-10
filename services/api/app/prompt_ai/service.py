"""AI prompt assistant (T081, FR-035 to FR-037, research R18).

Stateless: the browser sends the chat each time. Order of checks: replay of an
``Idempotency-Key`` (no new call, no new charge), 20 requests per minute per workspace (429),
balance at or below zero (402), the model call with a 60 s limit (504, never charged), then one
``billing.charge_feature("prompt_generation")`` per successful request.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from opentelemetry import trace
from redis.asyncio import Redis

from app.billing import service as billing
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError, too_many_requests
from app.core.rate_limit import RateLimiter
from app.llms.charges import charge_tokens
from app.llms.client import (
    ChatMessage,
    ModelError,
    ModelRef,
    ModelTimeout,
    token_cost,
)
from app.llms.runtime import CompletionClient
from app.pricing.engine import fmt6
from app.prompt_ai.proposal import parse_answer
from app.prompt_ai.schemas import GenerateRequest
from app.voices.catalog import load_catalog as load_voice_catalog

tracer = trace.get_tracer("app.prompt_ai")
SYSTEM_PROMPT = Path(__file__).with_name("system_prompt.md").read_text(encoding="utf-8")
PURPOSE = "prompt_assistant"
REPLAY_TTL_S = 24 * 3600
MAX_OUTPUT_TOKENS = 4000


def assistant_timeout() -> ProblemError:
    return ProblemError(
        504,
        "assistant_timeout",
        "Assistant did not answer",
        "The assistant did not answer in time. Nothing was charged; try again.",
    )


def build_system(request: GenerateRequest) -> str:
    language = load_voice_catalog().language(request.language)
    label = language.label if language else request.language
    parts = [SYSTEM_PROMPT, f"\nAgent language: {label} ({request.language})."]
    current = request.current
    if current is not None and (current.prompt or current.begin_message):
        parts.append("\nThe editor currently holds:")
        parts.append(f"<current_prompt>\n{current.prompt or ''}\n</current_prompt>")
        parts.append(f"<current_greeting>\n{current.begin_message or ''}\n</current_greeting>")
        if current.dynamic_variables:
            parts.append("Current variables: " + ", ".join(current.dynamic_variables))
    else:
        parts.append("\nThe agent has no prompt yet.")
    return "\n".join(parts)


async def generate(
    db: Database,
    redis: Redis,
    settings: Settings,
    client: CompletionClient,
    *,
    workspace_id: str,
    request: GenerateRequest,
    idempotency_key: str | None,
) -> dict[str, Any]:
    replay_key = f"idem:prompt_ai:{workspace_id}:{idempotency_key}" if idempotency_key else None
    if replay_key:
        cached = await redis.get(replay_key)
        if cached is not None:
            replayed: dict[str, Any] = json.loads(cached)
            return replayed
    limit = await RateLimiter(redis).hit(
        "prompt_ai", workspace_id, limit=settings.prompt_ai_rate_limit_per_min, window_s=60
    )
    if not limit.allowed:
        raise too_many_requests(limit.retry_after_s, "Too many assistant requests. Try again in a minute.")
    async with db.transaction(workspace_id=workspace_id) as session:
        if await billing.get_balance(session, workspace_id) <= 0:
            raise billing.insufficient_credit("Add funds to use the prompt assistant.")
    model_ref = ModelRef.parse(settings.prompt_ai_model)
    with tracer.start_as_current_span("prompt_ai.complete") as span:
        span.set_attribute("llm.model", f"{model_ref.provider}/{model_ref.model}")
        try:
            completion = await client.complete(
                model_ref,
                [ChatMessage(m.role, m.content) for m in request.messages],
                system=build_system(request),
                max_tokens=MAX_OUTPUT_TOKENS,
                timeout_s=settings.prompt_ai_timeout_s,
                json_mode=True,
                purpose=PURPOSE,
            )
        except (ModelTimeout, ModelError) as exc:
            span.record_exception(exc)
            raise assistant_timeout() from exc
    reply, proposal = parse_answer(completion.text)
    charge_key = f"prompt_ai:{idempotency_key or uuid.uuid4().hex}"
    async with db.transaction(workspace_id=workspace_id) as session:
        charge = await charge_tokens(
            session,
            workspace_id=workspace_id,
            feature_key="prompt_generation",
            idempotency_key=charge_key,
            tokens=completion.input_tokens + completion.output_tokens,
            raw_cost_usd=token_cost(model_ref.model, completion.input_tokens, completion.output_tokens),
            ref_type="agent" if request.agent_id else None,
            ref_id=request.agent_id,
        )
    billable = charge.usage_event.billable_cost_usd
    body = {"reply": reply, "proposal": proposal, "billed_usd": fmt6(billable)}
    if replay_key:
        await redis.set(replay_key, json.dumps(body), ex=REPLAY_TTL_S)
    return body
