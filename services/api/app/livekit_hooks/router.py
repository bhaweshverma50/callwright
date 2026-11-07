"""POST /v1/livekit/webhook (contracts/livekit_hooks.yaml, 003 T082).

Authenticated by LiveKit's JWT in ``Authorization`` (signed with the API secret) whose
``sha256`` claim must match the raw body; no user token.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

from app.core.errors import ProblemError, problem_responses
from app.core.livekit import WebhookAuthError
from app.core.queue import dispatch
from app.livekit_hooks import service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["livekit-hooks"])


@router.post("/livekit/webhook", responses=problem_responses(401))
async def receive_livekit_webhook(request: Request) -> Response:
    raw = (await request.body()).decode("utf-8", errors="replace")
    try:
        event = request.app.state.livekit.verify_webhook(raw, request.headers.get("authorization"))
    except WebhookAuthError as exc:
        logger.warning("livekit webhook rejected: %s", exc)
        raise ProblemError(
            401, "invalid_signature", "Not signed in", "Webhook signature is not valid."
        ) from exc
    outcome, deferred = await service.handle(request.app.state.db, event)
    await dispatch(getattr(request.app.state, "jobs", None), deferred)
    logger.info("livekit %s: %s", event.get("event"), outcome)
    return Response(status_code=200)
